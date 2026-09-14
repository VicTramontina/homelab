# homelab

Turns an old PC into an on-demand game server host, controlled entirely
from Discord. The PC stays off/asleep most of the time: it wakes via
Wake-on-LAN when someone wants to play, and shuts itself down again after
being idle, with backups to Cloudflare R2 happening right before anything
stops. First (and currently only) supported game: **HumanityZ**.

No always-on infrastructure beyond free-tier services -- the Discord bot
is a Cloudflare Worker (HTTP interactions, not a 24/7 gateway bot), and
MQTT signaling runs through Adafruit IO's free tier. Friends connect
through a [playit.gg](https://playit.gg) tunnel, so there's no router
port forwarding and no VPN required on their end.

See [`docs/architecture.md`](docs/architecture.md) for how the pieces fit
together (diagram, MQTT schemas, idle-detection/backup rules), and
[`docs/setup.md`](docs/setup.md) for the full step-by-step first-time
setup.

## Usage

| Command                | What it does                                                      |
|-------------------------|--------------------------------------------------------------------|
| `/start <game>`          | Wakes the PC if needed and starts that game's container            |
| `/stop <game>`           | Backs up and stops a running game                                   |
| `/status`                | Shows PC + all games' state, player counts, and last backup time    |
| `/status <game>`         | Same, for one game                                                   |
| `/backup <game>`         | Triggers an on-demand backup to R2                                   |

The `/status` embed also has **Start/Stop** and **Backup** buttons per
game for people who'd rather click than type.

## Repo layout

- `discord-bot/` -- Cloudflare Worker implementing the bot (HTTP
  interactions, slash commands + message components)
- `esp32-firmware/` -- Wake-on-LAN bridge firmware (PlatformIO/Arduino)
- `ansible/` -- provisions the Ubuntu Server LTS gameserver PC
- `server/` -- Docker Compose file for the game containers
- `docs/` -- architecture and setup documentation
