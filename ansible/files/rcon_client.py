"""Minimal Source RCON protocol client.

HumanityZ (and most Unreal-engine dedicated servers that expose RCON)
implement the same wire protocol as Valve's Source RCON
(https://developer.valvesoftware.com/wiki/Source_RCON_Protocol), so a
small hand-rolled client is enough -- no external dependency needed.

Shared by the status-daemon and activity-monitor roles.
"""
from __future__ import annotations

import socket
import struct

SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0


class RconError(Exception):
    pass


class RconClient:
    def __init__(self, host: str, port: int, password: str, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._request_id = 0

    def __enter__(self) -> "RconClient":
        self.connect()
        return self

    def __exit__(self, *exc_info):
        self.close()

    def connect(self) -> None:
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.settimeout(self.timeout)
        auth_id = self._send(SERVERDATA_AUTH, self.password)
        _, resp_id, _ = self._recv_packet()
        if resp_id != auth_id:
            self.close()
            raise RconError(f"RCON authentication failed for {self.host}:{self.port}")

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def command(self, text: str) -> str:
        if self._sock is None:
            raise RconError("RCON client is not connected")
        sent_id = self._send(SERVERDATA_EXECCOMMAND, text)
        _, resp_id, body = self._recv_packet()
        if resp_id != sent_id:
            raise RconError("RCON response id mismatch")
        return body

    def _send(self, pkt_type: int, body: str) -> int:
        self._request_id += 1
        req_id = self._request_id
        payload = struct.pack("<ii", req_id, pkt_type) + body.encode("utf-8") + b"\x00\x00"
        packet = struct.pack("<i", len(payload)) + payload
        assert self._sock is not None
        self._sock.sendall(packet)
        return req_id

    def _recv_packet(self) -> tuple[int, int, str]:
        assert self._sock is not None
        size_bytes = self._recvall(4)
        (size,) = struct.unpack("<i", size_bytes)
        body = self._recvall(size)
        req_id, pkt_type = struct.unpack("<ii", body[:8])
        text = body[8:-2].decode("utf-8", errors="replace")
        return pkt_type, req_id, text

    def _recvall(self, n: int) -> bytes:
        assert self._sock is not None
        data = b""
        while len(data) < n:
            chunk = self._sock.recv(n - len(data))
            if not chunk:
                raise RconError("RCON connection closed unexpectedly")
            data += chunk
        return data


def get_player_count(host: str, port: int, password: str, timeout: float = 5.0) -> int:
    """Query the HumanityZ "Players" RCON command and return the count.

    HumanityZ's Players command returns a human-readable list (one player
    per line, or an empty/"No players" style response when empty), so we
    count non-empty lines rather than parsing a structured format.
    """
    with RconClient(host, port, password, timeout=timeout) as client:
        response = client.command("Players")

    lines = [line.strip() for line in response.splitlines() if line.strip()]
    if not lines:
        return 0
    if len(lines) == 1 and "no player" in lines[0].lower():
        return 0
    return len(lines)
