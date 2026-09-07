# Architecture

## Overview

```
Discord (slash commands + buttons)
   |
   v
Cloudflare Worker (discord-bot/)
   - verifies Ed25519 request signature
   - publishes to the "server-command" feed (Adafruit IO / MQTT)
   - reads the "server-status" feed for /status
   |
   v
Adafruit IO (hosted MQTT broker + REST API)
   |                                   |
   v                                   v
ESP32 (esp32-firmware/)          game-manager (on the Ubuntu PC)
subscribes server-command        subscribes server-command
sends WoL magic packet for       executes the actual action:
any action != shutdown_pc        start/stop/backup/shutdown

Ubuntu Server LTS (headless, off most of the time)
   - status-daemon:     publishes server-status every ~90s
   - activity-monitor:  RCON player counts -> decides idle stop/shutdown
   - game-manager:      executes start/stop/backup/shutdown
   - backup-scheduler:  backup.sh, invoked by game-manager only
   - Docker Compose:    one service per game, none auto-start
```

Why an ESP32 in the loop at all: the gameserver PC is off or asleep most
of the time, so nothing running *on* that PC can wake it up. The ESP32 is
a cheap always-on device that just listens for MQTT messages and fires a
Wake-on-LAN magic packet. It does not need to know whether the PC is
already on -- a WoL packet sent to an already-running PC is a no-op, so
it reacts to every non-`shutdown_pc` action unconditionally.

## MQTT schema

### `server-command`

Published by the Worker (and by activity-monitor for automatic
stop/shutdown decisions). Subscribed to by both the ESP32 and
game-manager.

```json
{
  "action": "start_game",
  "target": "humanityz",
  "source": "discord",
  "user": "123456789012345678",
  "timestamp": "2026-09-07T14:30:00Z"
}
```

| Field       | Type            | Notes                                                                 |
|-------------|-----------------|------------------------------------------------------------------------|
| `action`    | string          | One of `start_game`, `stop_game`, `shutdown_pc`, `backup_game`         |
| `target`    | string or null  | Lowercase game name, or `null`/omitted for `shutdown_pc` (PC-wide)     |
| `source`    | string          | `"discord"` or `"activity-monitor"`                                    |
| `user`      | string          | Discord user id, or `"system"` for automatic actions                   |
| `timestamp` | string (ISO8601)| Used by game-manager to ignore stale/already-processed retained values |

Adafruit IO feeds are retained by default: the last published value is
delivered immediately to any new subscriber. game-manager relies on this
so that a `start_game` published while the PC was off is not lost -- when
the PC wakes and game-manager's systemd unit starts, its very first
message on this topic is that retained command.

### `server-status`

Published by status-daemon every ~90 seconds while the PC is on. Read by
the Worker to answer `/status`.

```json
{
  "pc_state": "on",
  "timestamp": "2026-09-07T14:30:00Z",
  "games": {
    "humanityz": {
      "state": "running",
      "players": 3,
      "max_players": 16,
      "last_backup": "2026-09-07T10:00:00Z"
    }
  }
}
```

status-daemon only runs while the PC is on, so `pc_state` is always
reported as `"on"`. There is intentionally no daemon publishing `"off"` --
a machine that's off can't run one. The Worker (or a human reading the
Discord embed) infers "probably off" from the feed simply going stale.

## Supported games

| Game       | Compose service | Game port(s)         | RCON port | Idle-stop threshold |
|------------|------------------|-----------------------|-----------|----------------------|
| HumanityZ  | `humanityz`      | 7777/udp, 27015/udp   | 8888/tcp  | 15 min, 0 players    |

Adding a game means: a new Docker Compose service, a new entry in
`ansible/group_vars/gameserver/vars.yml` (`games.<name>`), a new
`vault_rcon_pass_<name>` secret, and a new choice in
`discord-bot/src/commands.js`. No branching logic needs to be rewritten.

## Why backups only happen before stop/shutdown

The PC is off most of the time, so a fixed cron-style schedule (e.g.
"back up nightly at 3am") has no reliable window to actually run in --
the machine might be off at 3am, or mid-session, or about to be shut down
five minutes later anyway. Instead, a backup runs exactly at the two
moments the data is guaranteed to be about to go quiet: right before a
game container stops, and right before the whole PC shuts down. Both
paths go through the same `backup.sh` script, called by game-manager
before it runs `docker compose stop` or `shutdown -h now`. Manual,
on-demand backups (`/backup <game>`) use the same script directly.

## Idle detection

Idle detection is driven exclusively by RCON player counts (HumanityZ's
`Players` command over its Source-RCON-compatible protocol on port
8888), polled by activity-monitor every few minutes. Network-traffic
based fallback detection is intentionally not implemented.

- **15 minutes** with 0 players in a *running* game -> activity-monitor
  publishes `stop_game` for that game.
- **10 minutes** with *every* configured game stopped -> activity-monitor
  publishes `shutdown_pc`.

activity-monitor only publishes these intents to `server-command`; it
never stops a container or shuts the machine down itself. game-manager is
the single executor for all state changes, which is what guarantees the
backup-before-stop ordering above holds for automatic idle-driven
shutdowns too, not just manual commands.
