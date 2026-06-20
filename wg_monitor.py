#!/usr/bin/env python3
"""
WireGuard peer connection monitor — sends an alert whenever a peer connects
or disconnects. Runs every minute via cron on the Docker host.

Zero dependencies beyond the Python standard library.

Notification channels (set any combination — all active channels receive every alert):
  DISCORD_WEBHOOK   — Discord webhook URL
  SLACK_WEBHOOK     — Slack incoming webhook URL
  TELEGRAM_TOKEN    — Telegram bot token
  TELEGRAM_CHAT_ID  — Telegram chat / channel ID
  NTFY_URL          — ntfy topic URL  (e.g. https://ntfy.sh/my-topic)
  PUSHOVER_TOKEN    — Pushover application token
  PUSHOVER_USER     — Pushover user key
  GOTIFY_URL        — Gotify server URL (e.g. http://gotify:80)
  GOTIFY_TOKEN      — Gotify application token

Other settings:
  WG_CONTAINER      (default: wg-easy)
  STATE_FILE        (default: /opt/docker/wg-monitor/state.json)
  WG_CONFIG         (default: /var/lib/docker/volumes/wireguardeasy_etc_wireguard/_data/wg0.json)
  HANDSHAKE_TIMEOUT (default: 300 seconds)
"""
import subprocess, json, urllib.request, urllib.parse, os, re
from datetime import datetime, timezone

# ── Notification channels ─────────────────────────────────────────────────────
DISCORD_WEBHOOK  = os.getenv("DISCORD_WEBHOOK",  "")
SLACK_WEBHOOK    = os.getenv("SLACK_WEBHOOK",    "")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
NTFY_URL         = os.getenv("NTFY_URL",         "")
PUSHOVER_TOKEN   = os.getenv("PUSHOVER_TOKEN",   "")
PUSHOVER_USER    = os.getenv("PUSHOVER_USER",    "")
GOTIFY_URL       = os.getenv("GOTIFY_URL",       "")
GOTIFY_TOKEN     = os.getenv("GOTIFY_TOKEN",     "")

# ── WireGuard settings ────────────────────────────────────────────────────────
WG_CONTAINER      = os.getenv("WG_CONTAINER",  "wg-easy")
STATE_FILE        = os.getenv("STATE_FILE",    "/opt/docker/wg-monitor/state.json")
WG_CONFIG         = os.getenv("WG_CONFIG",     "/var/lib/docker/volumes/wireguardeasy_etc_wireguard/_data/wg0.json")
HANDSHAKE_TIMEOUT = int(os.getenv("HANDSHAKE_TIMEOUT", "300"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')


def _post_json(url, payload):
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "wg-monitor/1.0"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


# ── Per-channel senders ───────────────────────────────────────────────────────

def _discord(title, body, color):
    embed = {
        "title":       title,
        "description": body,
        "color":       color,
        "footer":      {"text": f"WireGuard · {_now()}"},
    }
    _post_json(DISCORD_WEBHOOK, {"embeds": [embed]})


def _slack(title, body):
    blocks = [
        {"type": "header",  "text": {"type": "plain_text", "text": title}},
        {"type": "section", "text": {"type": "mrkdwn",     "text": body}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"WireGuard · {_now()}"}]},
    ]
    _post_json(SLACK_WEBHOOK, {"blocks": blocks})


def _telegram(title, body):
    # Convert **bold** to *bold* for Telegram Markdown
    tg_body = re.sub(r'\*\*(.+?)\*\*', r'*\1*', body)
    text = f"*{title}*\n\n{tg_body}\n\n_WireGuard · {_now()}_"
    _post_json(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
    )


def _ntfy(title, body, color):
    priority = "urgent" if color == 0xFF4444 else "default"
    plain    = re.sub(r'[`*]', '', body)
    req = urllib.request.Request(
        NTFY_URL, data=plain.encode(),
        headers={
            "Title":        title,
            "Priority":     priority,
            "Content-Type": "text/plain",
            "User-Agent":   "wg-monitor/1.0",
        },
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


def _pushover(title, body, color):
    priority = 1 if color == 0xFF4444 else 0
    plain    = re.sub(r'[`*]', '', body)
    data = urllib.parse.urlencode({
        "token":    PUSHOVER_TOKEN,
        "user":     PUSHOVER_USER,
        "title":    title,
        "message":  plain,
        "priority": priority,
    }).encode()
    req = urllib.request.Request(
        "https://api.pushover.net/1/messages.json", data=data, method="POST"
    )
    urllib.request.urlopen(req, timeout=10)


def _gotify(title, body, color):
    priority = 8 if color == 0xFF4444 else 4
    plain    = re.sub(r'[`*]', '', body)
    _post_json(
        f"{GOTIFY_URL.rstrip('/')}/message?token={GOTIFY_TOKEN}",
        {"title": title, "message": plain, "priority": priority},
    )


def notify(title, body, color):
    """Dispatch to every configured channel. Errors in one don't block others."""
    channels = [
        (bool(DISCORD_WEBHOOK),                     lambda: _discord(title, body, color)),
        (bool(SLACK_WEBHOOK),                       lambda: _slack(title, body)),
        (bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID), lambda: _telegram(title, body)),
        (bool(NTFY_URL),                            lambda: _ntfy(title, body, color)),
        (bool(PUSHOVER_TOKEN and PUSHOVER_USER),    lambda: _pushover(title, body, color)),
        (bool(GOTIFY_URL and GOTIFY_TOKEN),         lambda: _gotify(title, body, color)),
    ]
    active = [fn for enabled, fn in channels if enabled]

    if not active:
        return

    for fn in active:
        try:
            fn()
        except Exception as e:
            print(f"Notification error: {e}")


# ── WireGuard ─────────────────────────────────────────────────────────────────

def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def get_transfer_raw():
    """Returns {pubkey: (rx_bytes, tx_bytes)} from `wg show transfer`."""
    r = subprocess.run(
        ["docker", "exec", WG_CONTAINER, "wg", "show", "wg0", "transfer"],
        capture_output=True, text=True,
    )
    result = {}
    for line in r.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) == 3:
            try:
                result[parts[0]] = (int(parts[1]), int(parts[2]))
            except ValueError:
                pass
    return result


def parse_handshake_age(s):
    if not s or "(none)" in s:
        return None
    m = re.search(r'(\d+)\s+(second|minute|hour|day)', s)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return n * {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[unit]


def get_wg_peers():
    r = subprocess.run(
        ["docker", "exec", WG_CONTAINER, "wg", "show"],
        capture_output=True, text=True,
    )
    peers, current = {}, None
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("peer:"):
            current = line.split(":", 1)[1].strip()
            peers[current] = {}
        elif current:
            for key in ("endpoint", "allowed ips", "latest handshake", "transfer"):
                if line.startswith(key + ":"):
                    peers[current][key] = line.split(":", 1)[1].strip()
    return peers


def get_peer_names():
    try:
        with open(WG_CONFIG) as f:
            config = json.load(f)
        return {c["publicKey"]: c.get("name", "Unknown")
                for c in config.get("clients", {}).values()}
    except Exception:
        return {}


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def tunnel_ip(peer_data):
    for part in peer_data.get("allowed ips", "").split(","):
        part = part.strip()
        if part.startswith("10."):
            return part.split("/")[0]
    return "?"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    peers     = get_wg_peers()
    names     = get_peer_names()
    state     = load_state()
    transfers = get_transfer_raw()
    alerts    = []
    new_state = {}

    for pubkey, data in peers.items():
        age           = parse_handshake_age(data.get("latest handshake", ""))
        is_connected  = age is not None and age < HANDSHAKE_TIMEOUT
        prev          = state.get(pubkey, {})
        was_connected = prev.get("connected", False)
        name          = names.get(pubkey, f"{pubkey[:12]}…")
        ip            = tunnel_ip(data)
        handshake     = data.get("latest handshake", "never")
        rx_now, tx_now = transfers.get(pubkey, (0, 0))

        new_state[pubkey] = {"connected": is_connected, "name": name}

        if is_connected and not was_connected:
            new_state[pubkey]["rx_at_connect"] = rx_now
            new_state[pubkey]["tx_at_connect"] = tx_now
            alerts.append((
                "🟢 WireGuard Connected",
                f"**{name}**\n🌐 Tunnel IP: `{ip}`\n📡 Handshake: {handshake}",
                0x00CC66,
            ))
        elif is_connected and was_connected:
            new_state[pubkey]["rx_at_connect"] = prev.get("rx_at_connect", rx_now)
            new_state[pubkey]["tx_at_connect"] = prev.get("tx_at_connect", tx_now)
        elif not is_connected and was_connected:
            rx0      = prev.get("rx_at_connect", rx_now)
            tx0      = prev.get("tx_at_connect", tx_now)
            upload   = fmt_bytes(max(0, rx_now - rx0))
            download = fmt_bytes(max(0, tx_now - tx0))
            alerts.append((
                "🔴 WireGuard Disconnected",
                f"**{name}**\n🌐 Tunnel IP: `{ip}`\n⏱️ Last handshake: {handshake}\n📊 Session: ↑ {upload} / ↓ {download}",
                0xFF4444,
            ))

    for pubkey, prev in state.items():
        if pubkey not in peers and prev.get("connected"):
            alerts.append((
                "🔴 WireGuard Disconnected",
                f"**{prev.get('name', pubkey[:12]+'…')}** — peer disappeared",
                0xFF4444,
            ))
            new_state[pubkey] = {"connected": False, "name": prev.get("name", "")}

    save_state(new_state)

    if alerts:
        for title, body, color in alerts:
            notify(title, body, color)
        print(f"{len(alerts)} state change(s)", flush=True)
    else:
        print("No state change", flush=True)


if __name__ == "__main__":
    main()
