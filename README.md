# wg-monitor

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/chabnco)

Discord alerting for [wg-easy](https://github.com/wg-easy/wg-easy) — sends a notification whenever a WireGuard peer connects or disconnects.

Runs every minute via cron on the Docker host. No daemon, no dependencies beyond the Python standard library.

## How it works

1. Runs `docker exec <wg-container> wg show` to get current peer handshake times.
2. Compares against the previous run's state (stored in `state.json`).
3. Sends a Discord embed for each connect/disconnect event.
4. Peer display names are resolved from the wg-easy config file (`wg0.json`).

## Requirements

- Python 3.8+
- Docker on the host (to exec into the wg-easy container)
- A Discord webhook URL
- wg-easy running as a Docker container

## Setup

### 1. Copy the script

```bash
mkdir -p /opt/docker/wg-monitor
cp wg_monitor.py /opt/docker/wg-monitor/wg_monitor.py
```

### 2. Set environment variables

The script reads its configuration from environment variables.  
For cron, create an env file at `/opt/docker/wg-monitor/.env`:

```
DISCORD_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN
WG_CONTAINER=wg-easy
STATE_FILE=/opt/docker/wg-monitor/state.json
WG_CONFIG=/var/lib/docker/volumes/wireguardeasy_etc_wireguard/_data/wg0.json
HANDSHAKE_TIMEOUT=300
```

### 3. Add to cron

```bash
# /etc/cron.d/wg-monitor
* * * * * root set -a; . /opt/docker/wg-monitor/.env; set +a; python3 /opt/docker/wg-monitor/wg_monitor.py >> /var/log/wg-monitor.log 2>&1
```

Or export the variables directly in the crontab:

```
* * * * * root DISCORD_WEBHOOK=https://... python3 /opt/docker/wg-monitor/wg_monitor.py >> /var/log/wg-monitor.log 2>&1
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_WEBHOOK` | *(required)* | Discord webhook URL |
| `WG_CONTAINER` | `wg-easy` | Name of the wg-easy Docker container |
| `STATE_FILE` | `/opt/docker/wg-monitor/state.json` | Path to persist peer state between runs |
| `WG_CONFIG` | `/var/lib/docker/volumes/wireguardeasy_etc_wireguard/_data/wg0.json` | Path to wg-easy's `wg0.json` (for peer names) |
| `HANDSHAKE_TIMEOUT` | `300` | Seconds after last handshake to consider a peer disconnected |

## Discord alerts

| Event | Color |
|-------|-------|
| Peer connected | 🟢 Green |
| Peer disconnected | 🔴 Red |

Each embed shows the peer name, tunnel IP, last handshake time, and transfer stats.

## Peer names

Peer names are resolved from wg-easy's `wg0.json` config file.  
The default path assumes a standard wg-easy Docker Compose setup with a named volume `wireguardeasy_etc_wireguard`.  
Adjust `WG_CONFIG` if your volume name differs.

## Compatibility

Tested with wg-easy v14 on Debian Bookworm (Raspberry Pi 5).  
Should work on any Linux host running wg-easy as a Docker container.

## License

MIT
