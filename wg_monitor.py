#!/usr/bin/env python3
"""WireGuard peer connection monitor → Discord alerts (runs every minute via cron)"""
import subprocess, json, urllib.request, os, re
from datetime import datetime, timezone

WEBHOOK           = os.environ["DISCORD_WEBHOOK"]
STATE_FILE        = os.getenv("STATE_FILE",  "/opt/docker/wg-monitor/state.json")
WG_CONFIG         = os.getenv("WG_CONFIG",   "/var/lib/docker/volumes/wireguardeasy_etc_wireguard/_data/wg0.json")
WG_CONTAINER      = os.getenv("WG_CONTAINER", "wg-easy")
HANDSHAKE_TIMEOUT = int(os.getenv("HANDSHAKE_TIMEOUT", "300"))  # seconds — peer "offline" after 5 min without handshake


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
        capture_output=True, text=True
    )
    peers = {}
    current = None
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
    """Read peer names from wg-easy config file (mounted on host)."""
    try:
        with open(WG_CONFIG) as f:
            config = json.load(f)
        return {
            c["publicKey"]: c.get("name", "Unknown")
            for c in config.get("clients", {}).values()
        }
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


def send_discord(embeds):
    data = json.dumps({"embeds": embeds[:10]}).encode()
    req = urllib.request.Request(
        WEBHOOK, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "curl/7.88.1"},
        method="POST"
    )
    urllib.request.urlopen(req, timeout=10)


def main():
    peers     = get_wg_peers()
    names     = get_peer_names()
    state     = load_state()
    now       = datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')
    embeds    = []
    new_state = {}

    for pubkey, data in peers.items():
        age          = parse_handshake_age(data.get("latest handshake", ""))
        is_connected = age is not None and age < HANDSHAKE_TIMEOUT
        was_connected = state.get(pubkey, {}).get("connected", False)
        name         = names.get(pubkey, f"{pubkey[:12]}…")
        ip           = tunnel_ip(data)
        transfer     = data.get("transfer", "—")
        handshake    = data.get("latest handshake", "never")

        new_state[pubkey] = {"connected": is_connected, "name": name}

        if is_connected and not was_connected:
            embeds.append({
                "title": "🟢 WireGuard Connected",
                "description": (
                    f"**{name}**\n"
                    f"🌐 Tunnel IP: `{ip}`\n"
                    f"📡 Handshake: {handshake}\n"
                    f"📊 Transfer: {transfer}"
                ),
                "color": 0x00CC66,
                "footer": {"text": f"WireGuard · {now}"},
            })
        elif not is_connected and was_connected:
            embeds.append({
                "title": "🔴 WireGuard Disconnected",
                "description": (
                    f"**{name}**\n"
                    f"🌐 Tunnel IP: `{ip}`\n"
                    f"⏱️ Last handshake: {handshake}"
                ),
                "color": 0xFF4444,
                "footer": {"text": f"WireGuard · {now}"},
            })

    # Peers removed from wg (edge case)
    for pubkey, prev in state.items():
        if pubkey not in peers and prev.get("connected"):
            embeds.append({
                "title": "🔴 WireGuard Disconnected",
                "description": f"**{prev.get('name', pubkey[:12]+'…')}** — peer disappeared",
                "color": 0xFF4444,
                "footer": {"text": f"WireGuard · {now}"},
            })
            new_state[pubkey] = {"connected": False, "name": prev.get("name", "")}

    save_state(new_state)

    if embeds:
        send_discord(embeds)
        print(f"{len(embeds)} alert(s) sent", flush=True)
    else:
        print("No state change", flush=True)


if __name__ == "__main__":
    main()
