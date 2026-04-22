"""HTTP client for the Mineflayer bridge REST API (localhost:3001)."""
from __future__ import annotations
import json
from pathlib import Path

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

    # ── FAWE / schematic endpoints (for /kasukabe-pixel) ────────────────────

    def fawe_check(self) -> dict:
        """GET /fawe_check — {installed, version, schem_dir_writable, schem_dir}.

        Returns dict with at least those keys. Raises on HTTP error.
        """
        r = requests.get(f"{self.base_url}/fawe_check", timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def fawe_per_player_config(self) -> dict:
        """GET /fawe_per_player_config — reads FAWE's config.yml.

        Returns dict with at least:
            per_player_schematics: bool | None   (None means bridge couldn't read config.yml)
            reason: str                          (present when flag is None or defaulted)
            config_path: str                     (present when file was located)

        Raises requests.HTTPError on transport failure. Callers should treat
        `per_player_schematics is True` as a hard stop — our upload/list path
        only sees the top-level schem dir, so per-player mode silently breaks
        the full-mode pipeline.
        """
        r = requests.get(
            f"{self.base_url}/fawe_per_player_config",
            timeout=DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()

    def fawe_schem_dir(self) -> str | None:
        """GET /fawe_schem_dir — absolute path to FAWE schematics dir, or None."""
        try:
            r = requests.get(f"{self.base_url}/fawe_schem_dir", timeout=DEFAULT_TIMEOUT)
            r.raise_for_status()
            return r.json().get("path")
        except Exception:
            return None

    def schem_list(self) -> list[str]:
        """Return the list of schematic basenames in FAWE's schematics dir.

        Uses the bridge's GET /fawe_schem_list (filesystem listing) rather
        than running `//schem list` via RCON. FAWE/WorldEdit route command
        output to the player chat packet, not to RCON's reply stream, so an
        RCON-based query always returns empty. What the canary actually
        needs to verify is "did the .schem file land in FAWE's scan
        directory" — which is a filesystem question.
        """
        r = requests.get(f"{self.base_url}/fawe_schem_list", timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        body = r.json()
        if "names" not in body:
            # Bridge predates /fawe_schem_list; fail loudly so the caller
            # sees "endpoint missing" rather than a silent empty list that
            # looks like "build.schem not uploaded".
            raise RuntimeError(
                "bridge /fawe_schem_list returned no 'names' field — "
                "bridge may need restart/upgrade"
            )
        return list(body["names"])

    def upload_schematic(self, local_path: Path) -> dict:
        """POST /upload_schematic — multipart upload of a .schem file.

        Server writes the file into the FAWE schematics directory.
        """
        local_path = Path(local_path)
        if not local_path.is_file():
            raise FileNotFoundError(local_path)
        with local_path.open("rb") as fh:
            files = {"file": (local_path.name, fh, "application/octet-stream")}
            r = requests.post(
                f"{self.base_url}/upload_schematic",
                files=files,
                timeout=60,
            )
        r.raise_for_status()
        return r.json()

    def validate_block(self, block_id: str) -> bool:
        """POST /validate_block — True if the server recognises the block id."""
        r = requests.post(
            f"{self.base_url}/validate_block",
            json={"block": block_id},
            timeout=DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        return bool(r.json().get("valid"))
