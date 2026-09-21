"""Player-count adapter for CS2 (Source RCON "status" command).

"status" prints a summary line before the per-player table --
"players : 2 humans, 3 bots (10/0 max)" -- so player count is read
straight off that line instead of parsing the table. Only humans count:
a server full of bots with zero humans should still look idle to
activity-monitor.

Source RCON responses larger than one packet get split across multiple
packets (see the Source RCON wiki's "Multiple-packet Responses"), which
rcon_client.RconClient.command() doesn't reassemble -- but the summary
line is always the first thing "status" prints, so it's expected to
survive even if a long player table gets truncated after it.
"""
import re

from rcon_client import RconError

_PLAYERS_RE = re.compile(r"players\s*:\s*(\d+)\s+humans?", re.IGNORECASE)


def get_player_count(client) -> int:
    response = client.command("status")

    match = _PLAYERS_RE.search(response)
    if not match:
        raise RconError(f"unexpected response to CS2 'status' command: {response!r}")
    return int(match.group(1))
