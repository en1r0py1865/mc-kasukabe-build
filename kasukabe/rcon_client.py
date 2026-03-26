import os
import socket
import struct
from typing import Optional


class RconError(RuntimeError):
    pass


class RconClient:
    def __init__(self, host: str, port: int, password: str, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self._connect_and_auth()

    def _connect_and_auth(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        self._send_packet(1, 3, self.password)
        req_id, packet_type, _ = self._read_packet()
        if req_id == -1 or packet_type not in (2, 0):
            raise RconError("RCON authentication failed")

    def _send_packet(self, req_id: int, packet_type: int, body: str) -> None:
        payload = struct.pack('<ii', req_id, packet_type) + body.encode('utf-8') + b'\x00\x00'
        packet = struct.pack('<i', len(payload)) + payload
        assert self.sock is not None
        self.sock.sendall(packet)

    def _read_packet(self):
        assert self.sock is not None
        raw_len = self._recv_exact(4)
        (length,) = struct.unpack('<i', raw_len)
        payload = self._recv_exact(length)
        req_id, packet_type = struct.unpack('<ii', payload[:8])
        body = payload[8:-2].decode('utf-8', errors='replace')
        return req_id, packet_type, body

    def _recv_exact(self, n: int) -> bytes:
        assert self.sock is not None
        chunks = []
        remaining = n
        while remaining > 0:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise RconError('RCON connection closed')
            chunks.append(chunk)
            remaining -= len(chunk)
        return b''.join(chunks)

    def command(self, command: str) -> str:
        self._send_packet(2, 2, command)
        req_id, packet_type, body = self._read_packet()
        if req_id == -1:
            raise RconError('RCON command rejected')
        return body

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None


def from_env() -> 'RconClient':
    """Create RconClient from environment variables.

    Raises RconError if CRAFTSMEN_RCON_PASSWORD is not set.
    """
    host = os.getenv('CRAFTSMEN_RCON_HOST', '127.0.0.1')
    port = int(os.getenv('CRAFTSMEN_RCON_PORT', '25575'))
    password = os.getenv('CRAFTSMEN_RCON_PASSWORD', '')
    if not password:
        raise RconError(
            "CRAFTSMEN_RCON_PASSWORD not set. "
            "Copy .env.example to .env and configure your RCON password."
        )
    return RconClient(host, port, password)
