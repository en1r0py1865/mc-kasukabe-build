"""HTTP client for the Mineflayer bridge REST API (localhost:3001)."""
from __future__ import annotations
import json
import requests

BRIDGE_URL = "http://localhost:3001"
DEFAULT_TIMEOUT = 10


class BridgeClient:
    """Thin wrapper around the Mineflayer bridge HTTP API."""

    def __init__(self, base_url: str = BRIDGE_URL):
        self.base_url = base_url.rstrip("/")

    def status(self) -> dict:
        """GET /status — connection state, position, health."""
        r = requests.get(f"{self.base_url}/status", timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def is_connected(self) -> bool:
        """Return True if bot is connected to the server."""
        try:
            return self.status().get("connected", False)
        except Exception:
            return False

    def move(self, x: int, y: int, z: int) -> dict:
        """POST /move — pathfind bot to coordinates."""
        r = requests.post(
            f"{self.base_url}/move",
            json={"x": x, "y": y, "z": z},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def send_command(self, command: str) -> dict:
        """POST /command — send a chat/slash command as the bot."""
        r = requests.post(
            f"{self.base_url}/command",
            json={"command": command},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def get_block(self, x: int, y: int, z: int) -> dict:
        """GET /block/:x/:y/:z — query block at absolute world coordinates."""
        r = requests.get(
            f"{self.base_url}/block/{x}/{y}/{z}",
            timeout=DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()

    def get_blocks_batch(self, positions: list[dict]) -> list[dict]:
        """POST /blocks — batch query up to 200 block positions.

        positions: list of {"x": int, "y": int, "z": int}
        Returns list of {"x", "y", "z", "block", "found"} dicts.
        """
        if len(positions) > 200:
            raise ValueError("max 200 positions per batch request")
        r = requests.post(
            f"{self.base_url}/blocks",
            json={"positions": positions},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("blocks", [])
