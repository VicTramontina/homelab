"""Player-count adapter for Windrose (no RCON, counts from container logs).

The dedicated server has no RCON, console or web API, so the count is
derived from the container's own log since its last start: a
"LogNet: Join succeeded: <player>" line adds a player and a
"LogNet: Leave: <player>" line removes them.

A miss in the leave direction over-counts (the game just never looks idle,
which is harmless). A miss in the join direction is the dangerous one, since
it would let activity-monitor stop a game with people in it. To cover that,
if connection markers show up in the log but no join line was ever matched,
the log format is treated as unrecognized and the pass is skipped instead of
reporting zero.
"""
import re
import subprocess

from rcon_client import RconError

_JOIN_RE = re.compile(r"LogNet: Join succeeded:\s*(.+?)\s*$", re.IGNORECASE)
_LEAVE_RE = re.compile(r"LogNet: Leave:\s*(.+?)\s*$", re.IGNORECASE)
_CONNECTION_MARKERS = ("login request", "notifyacceptingconnection", "notifyacceptedconnection")


def _run(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, text=True, check=False, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RconError(f"could not run {args[0]} {args[1]}: {exc}") from exc


def get_player_count_local(game: dict) -> int:
    service = game["compose_service"]

    inspect = _run(["docker", "inspect", "-f", "{{.State.StartedAt}}", service])
    if inspect.returncode != 0 or not inspect.stdout.strip():
        raise RconError(f"docker inspect failed for {service}: {inspect.stderr.strip()}")

    logs = _run(["docker", "logs", "--since", inspect.stdout.strip(), service])
    if logs.returncode != 0:
        raise RconError(f"docker logs failed for {service}: {logs.stderr.strip()}")

    online: set[str] = set()
    joins_seen = 0
    markers_seen = 0
    for line in (logs.stdout + "\n" + logs.stderr).splitlines():
        join = _JOIN_RE.search(line)
        if join:
            online.add(join.group(1))
            joins_seen += 1
            continue

        leave = _LEAVE_RE.search(line)
        if leave:
            online.discard(leave.group(1))
            continue

        lowered = line.lower()
        if any(marker in lowered for marker in _CONNECTION_MARKERS):
            markers_seen += 1

    if markers_seen and not joins_seen:
        raise RconError(
            f"{service} log shows {markers_seen} connection lines but no 'Join succeeded' line: "
            "log format not recognized, refusing to report 0 players"
        )
    return len(online)
