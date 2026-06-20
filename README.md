# wg-monitor

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/chabnco)

Multi-channel alerting for [wg-easy](https://github.com/wg-easy/wg-easy) — sends a notification whenever a WireGuard peer connects or disconnects.

Runs every minute via cron on the Docker host. No daemon, no dependencies beyond the Python standard library.  
**6 notification channels supported: Discord, Slack, Telegram, ntfy, Pushover, Gotify** — configure any combination.

## How it works

1. Runs `docker exec <wg-container> wg show` to get current peer handshake times.
2. Compares against the previous run's state (stored in `state.json`).
3. Sends an alert for each connect/disconnect event.
4. Peer display names are resolved from the wg-easy config file (`wg0.json`).

## Alerts

| Event | Color |
|-------|-------|
| 🟢 Peer connected | Green — tunnel IP, handshake time |
| 🔴 Peer disconnected | Red — tunnel IP, last handshake, **session upload/download** |

### Discord example

**Connection:**
```
┌─────────────────────────────────────┐
│ 🟢 WireGuard Connected              │
│─────────────────────────────────────│
│ Alice's iPhone                      │
│ 🌐 Tunnel IP: 10.8.0.2             │
│ 📡 Handshake: 3 seconds ago        │
│                                     │
│ WireGuard · 20/06/2026 18:00 UTC   │
└─────────────────────────────────────┘
```

**Disconnection:**
```
┌─────────────────────────────────────┐
│ 🔴 WireGuard Disconnected           │
│─────────────────────────────────────│
│ Alice's iPhone                      │
│ 🌐 Tunnel IP: 10.8.0.2             │
│ ⏱️ Last handshake: 5 minutes ago   │
│ 📊 Session: ↑ 24.3 MB / ↓ 1.2 GB  │
│                                     │
│ WireGuard · 20/06/2026 19:45 UTC   │
└─────────────────────────────────────┘
```

Upload (↑) = client → server. Download (↓) = server → client.

## Requirements

- Python 3.8+
- Docker on the host (to exec into the wg-easy container)
- At least one notification channel configured (see below)
- wg-easy running as a Docker container

## Setup

### 1. Copy the script

```bash
mkdir -p /opt/docker/wg-monitor
cp wg_monitor.py /opt/docker/wg-monitor/
```

### 2. Create an env file

```bash
# /opt/docker/wg-monitor/.env

# Notification channels — set any combination
DISCORD_WEBHOOK=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
SLACK_WEBHOOK=https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK
TELEGRAM_TOKEN=123456:ABCdef...
TELEGRAM_CHAT_ID=-1001234567890
NTFY_URL=https://ntfy.sh/your-private-topic
PUSHOVER_TOKEN=your_app_token
PUSHOVER_USER=your_user_key
GOTIFY_URL=http://gotify:80
GOTIFY_TOKEN=your_gotify_token

# Optional overrides
WG_CONTAINER=wg-easy
HANDSHAKE_TIMEOUT=300
```

### 3. Add to cron (every minute)

```bash
# /etc/cron.d/wg-monitor
* * * * * root set -a; . /opt/docker/wg-monitor/.env; set +a; python3 /opt/docker/wg-monitor/wg_monitor.py >> /var/log/wg-monitor.log 2>&1
```

## Notification channels

| Channel | Environment variables | Notes |
|---------|----------------------|-------|
| **Discord** | `DISCORD_WEBHOOK` | Rich embeds with color coding |
| **Slack** | `SLACK_WEBHOOK` | Block Kit layout |
| **Telegram** | `TELEGRAM_TOKEN` + `TELEGRAM_CHAT_ID` | Markdown formatting |
| **ntfy** | `NTFY_URL` | Priority: `urgent` on disconnect, `default` on connect |
| **Pushover** | `PUSHOVER_TOKEN` + `PUSHOVER_USER` | Priority 1 on disconnect, 0 on connect |
| **Gotify** | `GOTIFY_URL` + `GOTIFY_TOKEN` | Priority 8 on disconnect, 4 on connect |

All configured channels receive every alert. Errors in one channel don't block others.

### Getting a Telegram chat ID

```bash
# 1. Create a bot via @BotFather → get TELEGRAM_TOKEN
# 2. Send any message to your bot
# 3. Find your chat ID:
curl "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool | grep '"id"'
```

## Other settings

| Variable | Default | Description |
|----------|---------|-------------|
| `WG_CONTAINER` | `wg-easy` | Name of the wg-easy Docker container |
| `STATE_FILE` | `/opt/docker/wg-monitor/state.json` | Path to persist peer state between runs |
| `WG_CONFIG` | `/var/lib/docker/volumes/wireguardeasy_etc_wireguard/_data/wg0.json` | Path to wg-easy's `wg0.json` (for peer names) |
| `HANDSHAKE_TIMEOUT` | `300` | Seconds after last handshake to consider a peer disconnected |

## Peer names

Peer names are resolved from wg-easy's `wg0.json` config file.  
The default path assumes a standard wg-easy Docker Compose setup with a named volume `wireguardeasy_etc_wireguard`.  
Adjust `WG_CONFIG` if your volume name differs.

## Compatibility

Tested with wg-easy v14 on Debian Bookworm (Raspberry Pi 5).  
Should work on any Linux host running wg-easy as a Docker container.

## License

MIT
