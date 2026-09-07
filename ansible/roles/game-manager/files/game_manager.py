#!/usr/bin/env python3
"""Subscribes to server-command and executes the requested action.

This is the only component that actually changes state on the PC:
starting/stopping game containers, running backups, and shutting the
machine down. The ESP32 only wakes the PC; this script does the rest.

Adafruit IO feeds are retained, so subscribing always delivers the last
published value immediately (even if it was published while this PC was
still off). last_processed_command.json keeps track of the timestamp of
the last command we actually acted on, so a service restart doesn't
re-run an old command every time.
"""
import json
import ssl
import subprocess
import sys

import paho.mqtt.client as mqtt

CONFIG_PATH = "/opt/homelab/config.json"
STATE_PATH = "/opt/homelab/last_processed_command.json"
MQTT_HOST = "io.adafruit.com"
MQTT_PORT = 8883


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

    if action == "start_game" and target in config["games"]:
        compose(config, "start", config["games"][target]["compose_service"])

    elif action == "stop_game" and target in config["games"]:
        run_backup(config, target)
        compose(config, "stop", config["games"][target]["compose_service"])

    elif action == "backup_game" and target in config["games"]:
        run_backup(config, target)

    elif action == "shutdown_pc":
        for game in running_games(config):
            run_backup(config, game)
        print("game-manager: shutting down")
        subprocess.run(["shutdown", "-h", "now"], check=True)

    else:
        print(f"game-manager: ignoring unrecognized command {payload}", file=sys.stderr)


def on_connect(client: mqtt.Client, userdata: dict, flags, reason_code, properties=None) -> None:
    topic = f"{userdata['config']['aio_username']}/feeds/server-command"
    print(f"game-manager: connected, subscribing to {topic}")
    client.subscribe(topic)


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
