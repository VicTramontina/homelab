# Setup guide

Follow these steps in order. Each one produces a credential or value the
next step needs.

## 1. Adafruit IO (MQTT broker)

1. Create a free account at [io.adafruit.com](https://io.adafruit.com).
2. Create two feeds: **server-command** and **server-status** (Feeds ->
   New Feed). Default settings are fine; both are retained by default,
   which the system relies on.
3. Note your **Adafruit IO Username** and **Active Key** (io.adafruit.com
   -> click the yellow key icon). You'll need both in several places
   below.

## 2. Discord application and bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   and create a new application.
2. Note the **Application ID** (General Information tab) and the
   **Public Key** (same tab).
3. Bot tab -> create a bot, copy the **Bot Token**.
4. OAuth2 -> URL Generator -> scopes `bot` and `applications.commands`,
   no special bot permissions are required beyond sending messages in the
   channel you invite it to. Open the generated URL and invite the bot to
   your server.
5. Under General Information, set the **Interactions Endpoint URL** to
   your deployed Worker's URL (you'll get this in step 5, so come back to
   this after the Worker is deployed).

## 3. Cloudflare R2 (backup storage)

1. In the Cloudflare dashboard, go to R2 and create a bucket (e.g.
   `homelab-backups`).
2. Create an R2 API token (R2 -> Manage R2 API Tokens) with read/write
   access to that bucket. Note the **Access Key ID**, **Secret Access
   Key**, and your **Account ID** (used to build the S3-compatible
   endpoint: `https://<account_id>.r2.cloudflarestorage.com`).

## 4. playit.gg (no port forwarding, no VPN for friends)

This is what lets friends join over the internet without you touching
your router and without anyone installing a VPN. The `playit-agent`
Ansible role (step 8) installs an agent on the PC that connects out to
playit's network; you create the actual tunnel by hand, once, in their
dashboard.

1. Create a free account at [playit.gg](https://playit.gg).
2. Nothing to create by hand in the dashboard yet: the agent is claimed
   from the server itself in step 8 (`sudo playit setup`, which prints a
   link you approve in the browser). Don't create the agent in the
   dashboard as type "Docker" and paste its key in: run natively, it
   suffered periodic 5-10s UDP blackouts through the tunnel (measured
   with a UDP echo test), which dropped every CS2 session, while a
   natively claimed agent had none.
3. You can't create the tunnel itself until the agent has connected at
   least once, so this part comes back after step 8 (Ansible): once the
   `playit-agent` role has run and the agent shows as online in the
   dashboard, go to **Tunnels -> Create Tunnel** and create one tunnel
   per game, on the **claimed** agent, leaving the local address as
   `127.0.0.1` and keeping the local port equal to the game's own port:
   - HumanityZ: UDP, local port `7777`
   - CS2: **TCP+UDP** in a single tunnel (not two separate ones, which
     would get two different public addresses), local port `27015`
   - Windrose: **TCP+UDP** in a single tunnel, local port `7780`

   playit.gg assigns each tunnel a public address like
   `something.gl.at.ply.gg:12345` -- that's what you give your friends
   instead of your home IP (in CS2: `connect <address>; password <pw>`).
   Do not create a tunnel for the RCON ports (`8888` HumanityZ, `27016`
   CS2) -- they're only used locally and are firewalled/bound to
   loopback on purpose.

## 5. ESP32 firmware

1. Install [PlatformIO](https://platformio.org/) (VS Code extension or
   CLI).
2. In `esp32-firmware/include/`, copy `config.example.h` to `config.h`
   and fill in:
   - your 2.4GHz Wi-Fi SSID/password
   - your Adafruit IO username/key
   - the target PC's real MAC address (`TARGET_MAC_ADDR`) -- get it with
     `ip link show` on the PC (Linux) once Ubuntu is installed (step 7).
3. Flash it: `pio run -t upload` (with the ESP32 connected via USB).
4. Open the serial monitor (`pio device monitor`) and confirm it connects
   to Wi-Fi and to Adafruit IO's MQTT broker.

## 6. Cloudflare Worker (Discord bot)

1. `cd discord-bot && npm install`.
2. Authenticate wrangler: `npx wrangler login`.
3. Set the Worker secrets (never stored in the repo):
   ```
   npx wrangler secret put DISCORD_PUBLIC_KEY
   npx wrangler secret put AIO_USERNAME
   npx wrangler secret put AIO_KEY
   ```
4. Deploy: `npx wrangler deploy`. Note the `*.workers.dev` URL it prints.
5. Go back to the Discord Developer Portal (step 2.5) and set the
   **Interactions Endpoint URL** to `https://<your-worker>.workers.dev`.
   Discord will send a PING immediately -- if the Worker responds with
   PONG, the URL is accepted.
6. Register the slash commands for the first time:
   ```
   DISCORD_BOT_TOKEN=<bot token> DISCORD_APPLICATION_ID=<application id> \
     node scripts/register-commands.js
   ```
   Global commands can take up to an hour to show up the first time. Once
   the GitHub Actions secrets in step 9 are set, this re-runs
   automatically on every push to `discord-bot/**` (e.g. adding a game to
   `COMMAND_DEFINITIONS`), so this manual run is a one-time bootstrap.

## 7. Ubuntu Server LTS on the physical PC

1. Install [Ubuntu Server LTS](https://ubuntu.com/download/server)
   (headless is fine) on the old PC. During install, create a user with
   SSH access (or enable it afterwards with `apt install openssh-server`).
2. Enable Wake-on-LAN:
   - **BIOS/UEFI**: look for a "Wake on LAN" / "Power On by PCI-E" /
     "Resume by LAN" setting and enable it.
   - **Ubuntu**: find your wired interface name (`ip link show`), then:
     ```
     sudo apt install ethtool
     sudo ethtool <interface>   # check "Supports Wake-on: g" and "Wake-on: g"
     ```
     If `Wake-on` isn't `g`, enable it and persist it with a systemd-networkd
     link file or a NetworkManager dispatcher script, since it typically
     resets on reboot:
     ```
     sudo ethtool -s <interface> wol g
     ```
   - Note the interface's MAC address (`ip link show <interface>`) -- this
     is the `TARGET_MAC_ADDR` used in the ESP32 config (step 5).
3. Make sure the PC is on the same LAN segment/broadcast domain as the
   ESP32 (Wake-on-LAN magic packets are broadcast and don't cross
   routers/VLANs without extra config).

## 8. Ansible

Run this from any machine with SSH access to the Ubuntu server (your
laptop, or the server itself against `localhost`).

1. `cd ansible && ansible-galaxy collection install -r requirements.yml`.
2. Edit `inventory.ini` with the server's **current IP** (check with
   `hostname -I` on the server itself) and SSH user. The playbook
   installs mDNS (`avahi-daemon`) on this same run, so *after* it
   finishes once, switch `ansible_host` to `<hostname>.local` (e.g.
   `bigaserver.local`, check the server's hostname with `hostname`).
   That keeps working even if you change routers or the DHCP lease
   changes, unlike a hardcoded IP.
3. Edit `group_vars/gameserver/vars.yml`: set `aio_username`, `r2_bucket`,
   `r2_endpoint` (from step 3) to your real values.
4. Create the real vault file (values from steps 1, 3, and 4, plus a RCON
   password you choose yourself):
   ```
   ansible-vault create group_vars/gameserver/vault.yml
   ```
   Fill it in following the structure documented in
   `group_vars/gameserver/vault.yml.example`. `vault_discord_webhook_url`
   is optional: set it to get state-change notifications posted to a
   Discord channel (game started/stopped/backed up, PC shutting down),
   for both manual commands and automatic idle-triggered actions.
   Create one via Discord: Channel Settings -> Integrations -> Webhooks
   -> New Webhook -> Copy Webhook URL. Leave the key out of the vault
   entirely to skip notifications.
5. Run the playbook:
   ```
   ansible-playbook -i inventory.ini setup-server.yml --ask-vault-pass
   ```
   This installs mDNS (`avahi-daemon`, so the server is reachable at
   `<hostname>.local` from here on), Docker, creates the HumanityZ
   container (without starting it), writes `GameServerSettings.ini`
   with your chosen RCON password, installs and starts the `playit`
   agent, installs the Claude Code CLI, starts the netdata monitoring
   dashboard (reachable at `http://<hostname>.local:19999` from any
   machine on the LAN -- see `docs/architecture.md`), and
   installs/enables the three systemd services
   (`homelab-status-daemon`, `homelab-game-manager`,
   `homelab-activity-monitor`) plus `backup.sh`/rclone.
6. Claim the playit agent: SSH into the server and run `sudo playit setup`,
   then open the link it prints and approve it (pick the native/default
   agent type). This writes the agent's secret to `/etc/playit/playit.toml`;
   re-running the playbook never overwrites an existing one. Then, back in
   the playit.gg dashboard, the agent should show as online -- finish
   step 4.3 (create the tunnel) if you haven't yet.
7. Claude Code is installed but not authenticated (Ansible can't do that
   part -- it needs your own Claude account, not a vault secret). SSH in
   and run `claude`, then follow the browser login prompt; or set an
   `ANTHROPIC_API_KEY` if you'd rather authenticate non-interactively.

## 9. GitHub Actions secrets

In the repo's Settings -> Secrets and variables -> Actions, add:

- `CLOUDFLARE_API_TOKEN` -- a Cloudflare API token with permission to
  edit Workers (create one at
  [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens),
  template "Edit Cloudflare Workers"). Used by `deploy-worker.yml` to run
  `wrangler deploy` on every push to `discord-bot/**`.
- `DISCORD_BOT_TOKEN` and `DISCORD_APPLICATION_ID` -- the same values
  used for the manual `register-commands.js` run in step 6.6 (Discord
  Developer Portal -> your app -> Bot, and -> General Information).
  Used by the same workflow to re-run `register-commands.js` after every
  deploy, so a `COMMAND_DEFINITIONS` change (e.g. a new game) reaches
  Discord's `/start` `/stop` `/status` `/backup` dropdowns without a
  manual step.

## 10. Try it end to end

1. Shut the PC down (`sudo shutdown -h now` on the server, or just unplug
   the WoL test on an already-off machine).
2. In Discord: `/start humanityz`.
3. The Worker publishes `start_game` -> the ESP32 sends the WoL magic
   packet -> the PC boots -> `homelab-game-manager` starts, immediately
   sees the retained `start_game` command, and runs
   `docker compose start humanityz`.
4. `/status humanityz` a minute or two later should show `state: running`
   once status-daemon has published its first update.
5. Leave it idle (nobody connected) for 15+ minutes: activity-monitor
   should publish `stop_game`, game-manager backs up and stops it. Leave
   it idle for another 10 minutes with no games running: activity-monitor
   publishes `shutdown_pc`, game-manager backs up anything still running
   and shuts the PC down.
6. Check the R2 bucket -- you should see up to 3 timestamped
   `humanityz-<timestamp>.tar.gz` archives under a `humanityz/` prefix.
7. Have a friend connect using the playit.gg address from step 4.3
   (`something.gl.at.ply.gg:PORT`), not your home IP -- that's the whole
   point of the tunnel, nobody needs a VPN or your router touched.

## 11. Windrose: first start and player count

Windrose has no RCON, so its player count is parsed from the container
log (see `docs/architecture.md`, "Windrose").

- The first `/start` downloads about 3 GB, then the first player to join
  triggers world generation. On the current hardware that took about 5
  minutes, during which the game client can time out: if it drops, just
  reconnect, the world is saved and later joins are much faster. The
  15 minute idle-stop clock also runs during this, so join soon after
  `/start`.
- To check the count by hand: `docker logs windrose 2>&1 | grep -E
  "ReadyToPlay|Disconnect AccountId"` should show one ready line per
  join and one disconnect line per leave, and `/status windrose` should
  match.
