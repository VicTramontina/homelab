"""Player-count adapter for HumanityZ.

HumanityZ's "Players" RCON command returns a human-readable list (one
player per line, or a "No players" style line when empty) rather than a
structured format, so the count is derived by counting non-empty lines.
"""


def get_player_count(client) -> int:
    response = client.command("Players")

    lines = [line.strip() for line in response.splitlines() if line.strip()]
    if not lines:
        return 0
    if len(lines) == 1 and "no player" in lines[0].lower():
        return 0
    return len(lines)
