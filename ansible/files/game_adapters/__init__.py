"""Registry of per-game player-count adapters, keyed by game_type.

The RCON wire protocol (rcon_client.RconClient) is shared across every
Source-RCON-speaking game this project supports, but the command used to
list players and the shape of its response are not -- each adapter module
here owns that one game-specific detail behind a single function:
get_player_count(client: RconClient) -> int.

Adding a game whose RCON dialect isn't already covered by an existing
adapter means adding one small module here and registering it in
_ADAPTERS below. No other file (status-daemon, activity-monitor,
rcon_client.py) needs to change.
"""
import time

from rcon_client import RconClient, RconError

from . import cs2, humanityz

_ADAPTERS = {
    "humanityz": humanityz,
    "cs2": cs2,
}

# Reconnecting too soon after a previous RCON connection to the same
# server closed can get a bad response -- confirmed live against CS2: 8
# back-to-back reconnects got ~40% empty responses, 8 reconnects spaced
# 1s apart got zero. Normal polling (status-daemon/activity-monitor, tens
# of seconds apart) never hits this in practice, but a single retry
# covers the rare case of two queries landing close together.
_RETRY_DELAY_SECONDS = 1.0


def get_player_count(host: str, port: int, password: str, game_type: str, timeout: float = 5.0) -> int:
    try:
        adapter = _ADAPTERS[game_type]
    except KeyError:
        raise RconError(
            f"no player-count adapter registered for game_type '{game_type}' "
            f"(known: {', '.join(sorted(_ADAPTERS))})"
        ) from None

    for attempt in range(2):
        try:
            with RconClient(host, port, password, timeout=timeout) as client:
                return adapter.get_player_count(client)
        except RconError:
            if attempt == 0:
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            raise
