#!/usr/bin/env python3
"""Decides when a game or the whole PC has been idle long enough to stop.

Idleness is measured purely by RCON player counts, per game:
  - 15 minutes with zero players in a running game -> publish stop_game
  - 10 minutes with every configured game stopped   -> publish shutdown_pc

This script only *publishes intents* to server-command; game-manager is
the one that actually stops containers / runs backups / shuts down, so
backups always happen before anything stops (see docs/architecture.md).
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/opt/homelab")
from game_adapters import get_player_count  # noqa: E402
from rcon_client import RconError  # noqa: E402

CONFIG_PATH = "/opt/homelab/config.json"
STATE_PATH = "/opt/homelab/activity_state.json"
POLL_INTERVAL_SECONDS = 180
GAME_IDLE_TIMEOUT = timedelta(minutes=15)
PC_IDLE_TIMEOUT = timedelta(minutes=10)


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


def is_container_running(container_name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def publish_command(config: dict, action: str, target: str | None) -> None:
    payload = {
        "action": action,
        "target": target,
        "source": "activity-monitor",
        "user": "system",
        "timestamp": now_iso(),
    }
    url = f"https://io.adafruit.com/api/v2/{config['aio_username']}/feeds/server-command/data"
    body = json.dumps({"value": json.dumps(payload)}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-AIO-Key": config["aio_key"]},
    )
    print(f"activity-monitor: publishing {action} target={target}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def check_games(config: dict, state: dict) -> list[str]:
    """Returns the list of games still running after this pass."""
    still_running = []
    for name, game in config["games"].items():
        if not is_container_running(game["compose_service"]):
            state["last_seen_with_players"].pop(name, None)
            continue

        still_running.append(name)
        try:
            players = get_player_count(
                game["rcon_host"], game["rcon_port"], game["rcon_pass"], game["game_type"]
            )
        except (RconError, OSError) as exc:
            print(f"activity-monitor: RCON query failed for {name}, skipping this pass: {exc}", file=sys.stderr)
            continue

        if players > 0:
            state["last_seen_with_players"][name] = now_iso()
            continue

        last_seen = state["last_seen_with_players"].get(name)
        if last_seen is None:
            state["last_seen_with_players"][name] = now_iso()
        elif now() - parse_iso(last_seen) >= GAME_IDLE_TIMEOUT:
            publish_command(config, "stop_game", name)
            state["last_seen_with_players"].pop(name, None)

    return still_running


def check_pc(config: dict, state: dict, still_running: list[str]) -> None:
    if still_running:
        state["all_stopped_since"] = None
        return

    if state["all_stopped_since"] is None:
        state["all_stopped_since"] = now_iso()
        return

    if now() - parse_iso(state["all_stopped_since"]) >= PC_IDLE_TIMEOUT:
        publish_command(config, "shutdown_pc", None)
        state["all_stopped_since"] = None


def main() -> None:
    config = load_config()
    # Always start with a clean idle-clock instead of trusting whatever was
    # last written to STATE_PATH: this process only runs while the PC is
    # on, so a persisted "since" timestamp always predates this boot --
    # trusting it would make a freshly-booted PC see its own idle window as
    # already expired and immediately fire stop_game/shutdown_pc before
    # anything gets a fair chance to run. Still written to STATE_PATH
    # during operation (see save_state) so it's inspectable and survives a
    # same-boot crash-restart, just never trusted across a reboot.
    state = {"last_seen_with_players": {}, "all_stopped_since": None}

    while True:
        try:
            still_running = check_games(config, state)
            check_pc(config, state, still_running)
            save_state(state)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            print(f"activity-monitor: error: {exc}", file=sys.stderr)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
