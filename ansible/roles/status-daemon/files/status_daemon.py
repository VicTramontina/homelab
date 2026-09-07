#!/usr/bin/env python3
"""Publishes the server-status feed to Adafruit IO every 90 seconds.

Reads game state via `docker inspect`, player counts via RCON, and the
last backup timestamp from /opt/homelab/last_backup_<game>.txt (written
by backup.sh). This only runs while the PC is on, so pc_state is always
reported as "on" -- the absence of recent updates to this feed is itself
the signal (to a human, or to the Worker if it wants to infer staleness)
that the PC is off.
"""
import datetime
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/homelab")
from rcon_client import RconError, get_player_count  # noqa: E402

CONFIG_PATH = "/opt/homelab/config.json"
POLL_INTERVAL_SECONDS = 90


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def is_container_running(container_name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def read_last_backup(config: dict, game: str) -> str | None:
    path = f"{config['homelab_dir']}/last_backup_{game}.txt"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def build_status(config: dict) -> dict:
    games = {}
    for name, game in config["games"].items():
        running = is_container_running(game["compose_service"])
        players = 0
        if running:
            try:
                players = get_player_count(game["rcon_host"], game["rcon_port"], game["rcon_pass"])
            except (RconError, OSError) as exc:
                print(f"status-daemon: RCON query failed for {name}: {exc}", file=sys.stderr)
        games[name] = {
            "state": "running" if running else "stopped",
            "players": players,
            "max_players": game["max_players"],
            "last_backup": read_last_backup(config, name),
        }

    return {
        "pc_state": "on",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "games": games,
    }


def publish(config: dict, status: dict) -> None:
    url = f"https://io.adafruit.com/api/v2/{config['aio_username']}/feeds/server-status/data"
    body = json.dumps({"value": json.dumps(status)}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-AIO-Key": config["aio_key"]},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def main() -> None:
    config = load_config()
    while True:
        try:
            status = build_status(config)
            publish(config, status)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            print(f"status-daemon: error: {exc}", file=sys.stderr)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
