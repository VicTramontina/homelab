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
   - playit-agent:      outbound-only tunnel, no router port forwarding
   - Docker Compose:    one service per game (none auto-start), plus netdata (auto-starts)

Friends -----> playit.gg relay -----> playit-agent -----> game port (local)
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

## Monitoring dashboard (netdata)

[netdata](https://www.netdata.cloud/) runs as its own Docker Compose
service (`server/docker-compose.yml`), giving a real-time, zero-config
dashboard of the PC itself (CPU, RAM, disk, network, temperatures) plus
per-container stats for `humanityz`/`cs2` (auto-discovered via a
read-only mount of `/var/run/docker.sock`).

It's the one compose service that behaves unlike the games: it uses
`restart: unless-stopped` and is started explicitly by the `docker` role
right after provisioning, so it comes up on its own whenever the PC wakes
-- there's no on-demand start/stop for it, and `game-manager` /
`activity-monitor` don't know it exists.

Reachable at `http://<hostname>.local:19999` (e.g. `bigaserver.local`)
from any machine on the same LAN, over the mDNS name the `mdns` role
sets up. Bound to all interfaces like the game ports, relying on the
same "no port forwarding on the router" invariant described below --
**not** tunneled through playit.gg like the game ports, since the
dashboard has no authentication of its own.

## Networking: no port forwarding

The PC sits behind a home router the owner doesn't want to touch (no port
forwarding, no DDNS, no exposing the router's admin panel to figure out
UPnP quirks), and friends shouldn't need a VPN just to join a game. Both
constraints are solved by [playit.gg](https://playit.gg): the
`playit-agent` role installs its Linux agent as a systemd service, which
makes a single outbound connection to playit's relay network -- the same
NAT-traversal trick tools like ngrok or Tailscale Funnel use. No inbound
port ever needs to be opened on the router for this to work.

Tunnels (which local port maps to which public playit.gg address) are
configured once, by hand, in the playit.gg web dashboard -- not in this
repo -- because they're tied to the agent's account-level secret key, not
to anything Ansible manages locally. See `docs/setup.md` for the
one-time dashboard steps. The agent is claimed once on the server with
`sudo playit setup`, which writes its secret to `/etc/playit/playit.toml`;
the role never overwrites an existing file (`vault_playit_secret_key` is
only an optional seed for a brand-new box).

Only the actual game port is tunneled. RCON (8888/tcp) is deliberately
**never** tunneled -- it's only ever used locally, by status-daemon and
activity-monitor over `127.0.0.1` -- so `server/docker-compose.yml` binds
it to loopback only (`127.0.0.1:8888:8888`) rather than exposing it on
every interface.

## Supported games

| Game       | Game type   | Compose service | Game port(s)         | RCON port          | Idle-stop threshold |
|------------|-------------|------------------|-----------------------|---------------------|----------------------|
| HumanityZ  | `humanityz` | `humanityz`      | 7777/udp, 27017/udp   | 8888/tcp            | 15 min, 0 players    |
| CS2        | `cs2`       | `cs2`            | 27015/tcp+udp         | 27016/tcp (CS2_RCON_PORT) | 15 min, 0 humans (bots don't count) |

Adding a game means: a new Docker Compose service, a new entry in
`ansible/group_vars/gameserver/vars.yml` (`games.<name>`, including a
`game_type`), a new `vault_rcon_pass_<name>` secret, and a new choice in
`discord-bot/src/commands.js`. None of `game-manager`, `status-daemon`,
`activity-monitor` or `backup.sh` need any changes -- they're all driven
generically by `config.json`.

The one thing that *is* genuinely per-game, because different server
software disagrees on both its config file format and its RCON dialect,
is `game_type`. It selects two small "adapter" files:

- `ansible/roles/docker/tasks/games/<game_type>.yml` -- generates that
  game's on-disk server config (whatever format it expects: `.ini`,
  `.yaml`, env file...). Included by `roles/docker/tasks/main.yml` for
  every `games.<name>` entry, keyed by its `game_type`.
- `ansible/files/game_adapters/<game_type>.py` -- knows the RCON command
  to list players and how to parse the response, behind one function:
  `get_player_count(client) -> int`. Registered in
  `ansible/files/game_adapters/__init__.py`. `rcon_client.py` itself only
  implements the shared Source RCON wire protocol and has no per-game
  knowledge.

CS2 illustrates the "env file" flavor of the first adapter: its image
regenerates any on-disk config from env vars on every start, so instead
of templating a mounted config file (HumanitZ's approach), `games/cs2.yml`
renders a `server/<name>.env` file (gitignored -- see
`server/docker-compose.yml`'s comment) that the compose service loads via
`env_file:`. That's what keeps its secrets (RCON password, join password,
GSLT) out of the git-committed compose file.

Reuse an existing `game_type` (e.g. a modded variant of the same server
software) if both dialects match; otherwise add one new pair of adapter
files -- everything else stays generic.

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
