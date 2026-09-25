"""Player-count adapter for Windrose (no RCON, counts from container logs).

The dedicated server has no RCON, console or web API, so the count is
derived from the container's own log. A player is online from the line
"OnClientIsReady  Client id ReadyToPlay. AccountId <id>" (the client has
finished loading, which is when it actually counts as playing) until a
"Disconnect AccountId <id>" or "Account disconnected. AccountId <id>" line.
Players still loading are not counted.

The log is very verbose and Docker rotates it, so the online set is kept in
memory and each call only reads what was logged since the previous one; a
full re-read (from the container's last start) happens only when the
container restarts or the daemon itself starts. That keeps a long-connected
player from vanishing from the count when their join line rotates out.

If connection attempts show up in the log but no ready line was ever seen,
the log format is treated as unrecognized and the pass is skipped instead of
reporting zero, so activity-monitor can't stop a game with people in it.
"""
import re
import subprocess
from datetime import datetime, timedelta, timezone

from rcon_client import RconError

_READY_RE = re.compile(r"Client id ReadyToPlay\.\s+AccountId\s+(\w+)")
_LEAVE_RE = re.compile(r"(?:Disconnect AccountId|Account disconnected\.\s+AccountId)\s+(\w+)")
_LOGIN_MARKER = "login request"
_OVERLAP = timedelta(seconds=5)

_state: dict[str, dict] = {}


def _run(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False, timeout=20
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RconError(f"could not run {args[0]} {args[1]}: {exc}") from exc


def _read_new_lines(service: str, since: str) -> list[str]:
    logs = _run(["docker", "logs", "--since", since, service])
    if logs.returncode != 0:
        raise RconError(f"docker logs failed for {service}: {logs.stdout.strip()[-200:]}")
    return logs.stdout.splitlines()


def get_player_count_local(game: dict) -> int:
    service = game["compose_service"]

    inspect = _run(["docker", "inspect", "-f", "{{.State.StartedAt}}", service])
    started_at = inspect.stdout.strip()
    if inspect.returncode != 0 or not started_at:
        raise RconError(f"docker inspect failed for {service}: {started_at}")

    state = _state.get(service)
    if state is None or state["started_at"] != started_at:
        state = {"started_at": started_at, "cursor": started_at, "online": set(), "ready_seen": 0, "logins_seen": 0}
        _state[service] = state

    poll_started = datetime.now(timezone.utc)
    for line in _read_new_lines(service, state["cursor"]):
        ready = _READY_RE.search(line)
        if ready:
            state["online"].add(ready.group(1))
            state["ready_seen"] += 1
            continue

        leave = _LEAVE_RE.search(line)
        if leave:
            state["online"].discard(leave.group(1))
            continue

        if _LOGIN_MARKER in line.lower():
            state["logins_seen"] += 1

    state["cursor"] = (poll_started - _OVERLAP).strftime("%Y-%m-%dT%H:%M:%SZ")

    if state["logins_seen"] and not state["ready_seen"]:
        raise RconError(
            f"{service} log shows {state['logins_seen']} login requests but no 'ReadyToPlay' line: "
            "still loading or log format not recognized, refusing to report 0 players"
        )
    return len(state["online"])
