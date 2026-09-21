#!/usr/bin/env python3
"""Subscribes to server-command and executes the requested action.

This is the only component that actually changes state on the PC:
starting/stopping game containers, running backups, and shutting the
machine down. The ESP32 only wakes the PC; this script does the rest.

Adafruit IO does NOT implement real MQTT retain (it doesn't store data in
the broker) -- a plain subscribe does NOT deliver the last published
value. Instead, per their MQTT API docs, a client has to publish an
empty message to "<topic>/get" right after subscribing, and Adafruit IO
replies with the current value just for that client. That's the only way
this process -- which doesn't exist until the PC it runs on has already
booted -- can catch a command that was published while the PC was still
off, which is the main way this project gets used. last_processed_command.json
keeps track of the timestamp of the last command we actually acted on,
so a service restart doesn't re-run an old command every time.
"""
import json
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

import paho.mqtt.client as mqtt

CONFIG_PATH = "/opt/homelab/config.json"
STATE_PATH = "/opt/homelab/last_processed_command.json"
MQTT_HOST = "io.adafruit.com"
MQTT_PORT = 8883
READY_TIMEOUT_SECONDS = 300
READY_POLL_INTERVAL_SECONDS = 5


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_last_processed_ts() -> str:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("timestamp", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return ""


def save_last_processed_ts(ts: str) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"timestamp": ts}, f)


def compose(config: dict, *args: str) -> None:
    cmd = ["docker", "compose", "-f", f"{config['compose_dir']}/docker-compose.yml", *args]
    print(f"game-manager: running {' '.join(cmd)}")
    subprocess.run(cmd, cwd=config["compose_dir"], check=True)


def run_backup(config: dict, game: str) -> None:
    if game not in config["games"]:
        print(f"game-manager: unknown game '{game}', skipping backup", file=sys.stderr)
        return
    print(f"game-manager: backing up {game}")
    subprocess.run([f"{config['homelab_dir']}/backup.sh", game], check=True)


def notify_discord(config: dict, message: str) -> None:
    webhook_url = config.get("discord_webhook_url")
    if not webhook_url:
        return
    body = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            # Discord's edge rejects Python's default "Python-urllib/x.y"
            # User-Agent with a 403, unrelated to the webhook itself.
            "User-Agent": "homelab-game-manager/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except (urllib.error.URLError, OSError) as exc:
        print(f"game-manager: failed to notify Discord: {exc}", file=sys.stderr)


def describe_source(payload: dict) -> str:
    if payload.get("source") == "activity-monitor":
        return "due to inactivity"
    user = payload.get("user")
    return f"by <@{user}>" if user and user != "system" else "manually"


def game_label(config: dict, game: str) -> str:
    return config["games"][game].get("label", game)


def wait_for_ready(config: dict, game: str) -> bool:
    """Poll until the container is healthy (or just running, for images
    with no healthcheck defined) or READY_TIMEOUT_SECONDS elapses."""
    service = config["games"][game]["compose_service"]
    deadline = time.time() + READY_TIMEOUT_SECONDS
    while time.time() < deadline:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                service,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            running, _, health = result.stdout.strip().partition("|")
            if running == "true" and health in ("healthy", "none"):
                return True
        time.sleep(READY_POLL_INTERVAL_SECONDS)
    return False


def running_games(config: dict) -> list[str]:
    running = []
    for name, game in config["games"].items():
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", game["compose_service"]],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == "true":
            running.append(name)
    return running


def handle_command(config: dict, payload: dict) -> None:
    action = payload.get("action")
    target = payload.get("target")
    source_desc = describe_source(payload)

    if action == "start_game" and target in config["games"]:
        label = game_label(config, target)
        compose(config, "start", config["games"][target]["compose_service"])
        if wait_for_ready(config, target):
            notify_discord(config, f"✅ **{label}** is up and ready to play!")
        else:
            notify_discord(
                config,
                f"⚠️ **{label}** is taking longer than expected to start. Check `/status`.",
            )

    elif action == "stop_game" and target in config["games"]:
        label = game_label(config, target)
        run_backup(config, target)
        compose(config, "stop", config["games"][target]["compose_service"])
        notify_discord(config, f"⏸️ **{label}** stopped ({source_desc}), backup done.")

    elif action == "backup_game" and target in config["games"]:
        label = game_label(config, target)
        run_backup(config, target)
        notify_discord(config, f"💾 Backup of **{label}** completed.")

    elif action == "shutdown_pc":
        for game in running_games(config):
            run_backup(config, game)
        notify_discord(config, f"🌙 PC shutting down ({source_desc}), all backups done.")
        print("game-manager: shutting down")
        subprocess.run(["shutdown", "-h", "now"], check=True)

    else:
        print(f"game-manager: ignoring unrecognized command {payload}", file=sys.stderr)


def on_connect(client: mqtt.Client, userdata: dict, flags, reason_code, properties=None) -> None:
    topic = f"{userdata['config']['aio_username']}/feeds/server-command"
    print(f"game-manager: connected, subscribing to {topic}")
    client.subscribe(topic)
    # Adafruit IO has no real MQTT retain -- ask it to resend the current
    # value just for us (see module docstring). Without this, a command
    # published while the PC was off is silently missed forever: this
    # process doesn't exist to receive it live, and nothing else re-sends it.
    client.publish(f"{topic}/get", payload="")


def on_message(client: mqtt.Client, userdata: dict, msg: mqtt.MQTTMessage) -> None:
    config = userdata["config"]
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"game-manager: bad payload: {exc}", file=sys.stderr)
        return

    ts = payload.get("timestamp", "")
    last_ts = userdata["last_processed_ts"]
    if ts and last_ts and ts <= last_ts:
        print(f"game-manager: skipping already-processed/stale command ({ts})")
        return

    try:
        handle_command(config, payload)
    except subprocess.CalledProcessError as exc:
        print(f"game-manager: command failed: {exc}", file=sys.stderr)
    finally:
        if ts:
            userdata["last_processed_ts"] = ts
            save_last_processed_ts(ts)


def main() -> None:
    config = load_config()
    userdata = {"config": config, "last_processed_ts": load_last_processed_ts()}

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata=userdata)
    client.username_pw_set(config["aio_username"], config["aio_key"])
    client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
