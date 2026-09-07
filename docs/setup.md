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

## 4. ESP32 firmware

1. Install [PlatformIO](https://platformio.org/) (VS Code extension or
   CLI).
2. In `esp32-firmware/include/`, copy `config.example.h` to `config.h`
   and fill in:
   - your 2.4GHz Wi-Fi SSID/password
   - your Adafruit IO username/key
   - the target PC's real MAC address (`TARGET_MAC_ADDR`) -- get it with
     `ip link show` on the PC (Linux) once Ubuntu is installed (step 6).
3. Flash it: `pio run -t upload` (with the ESP32 connected via USB).
4. Open the serial monitor (`pio device monitor`) and confirm it connects
   to Wi-Fi and to Adafruit IO's MQTT broker.

## 5. Cloudflare Worker (Discord bot)

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
6. Register the slash commands (run locally, not deployed):
   ```
   DISCORD_BOT_TOKEN=<bot token> DISCORD_APPLICATION_ID=<application id> \
     node scripts/register-commands.js
   ```
   Global commands can take up to an hour to show up the first time.

## 6. Ubuntu Server LTS on the physical PC

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
     is the `TARGET_MAC_ADDR` used in the ESP32 config (step 4).
3. Make sure the PC is on the same LAN segment/broadcast domain as the
   ESP32 (Wake-on-LAN magic packets are broadcast and don't cross
   routers/VLANs without extra config).

## 7. Ansible

Run this from any machine with SSH access to the Ubuntu server (your
laptop, or the server itself against `localhost`).

1. `cd ansible && ansible-galaxy collection install -r requirements.yml`.
2. Edit `inventory.ini` with the real IP/hostname and SSH user for the
   server.
3. Edit `group_vars/gameserver/vars.yml`: set `aio_username`, `r2_bucket`,
   `r2_endpoint` (from step 3) to your real values.
4. Create the real vault file (values from steps 1 and 3, plus a RCON
   password you choose yourself):
   ```
   ansible-vault create group_vars/gameserver/vault.yml
   ```
   Fill it in following the structure documented in
   `group_vars/gameserver/vault.yml.example`.
5. Run the playbook:
   ```
   ansible-playbook -i inventory.ini setup-server.yml --ask-vault-pass
   ```
   This installs Docker, creates the HumanityZ container (without
   starting it), writes `GameServerSettings.ini` with your chosen RCON
   password, and installs/enables the three systemd services
   (`homelab-status-daemon`, `homelab-game-manager`,
   `homelab-activity-monitor`) plus `backup.sh`/rclone.

## 8. GitHub Actions secrets

In the repo's Settings -> Secrets and variables -> Actions, add:

- `CLOUDFLARE_API_TOKEN` -- a Cloudflare API token with permission to
  edit Workers (create one at
  [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens),
  template "Edit Cloudflare Workers"). Used by `deploy-worker.yml` to run
  `wrangler deploy` on every push to `discord-bot/**`.

## 9. Try it end to end

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
