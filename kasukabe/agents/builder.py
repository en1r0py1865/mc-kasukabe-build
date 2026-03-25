"""Builder agent — executes commands.txt via RCON and Mineflayer bridge."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

from kasukabe.rcon_client import RconClient

# ── Constants ─────────────────────────────────────────────────────────────────

BRIDGE_URL = "http://localhost:3001"
RCON_HOST = "127.0.0.1"
RCON_PORT = 25575
RCON_PASSWORD = "minecraft123"

VANILLA_DELAY = 0.15   # seconds between RCON commands
BRIDGE_DELAY = 0.10    # seconds between bridge commands

# Patterns from minecraft-public-workflow/code/rcon_send.py
_CHANGED_RE = re.compile(
    r"(?:Changed|Successfully\s+filled)\s+(\d+)\s+(?:blocks?|block\(s\))",
    re.IGNORECASE,
)
_ERROR_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"unknown command",
        r"incorrect argument",
        r"invalid",
        r"not loaded",
        r"out of the world",
        r"command was not found",
    ]
]
_BENIGN_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"no blocks were filled",  # setting air where air already is — ok
    ]
]

_WORLDEDIT_HEADER = re.compile(r"^#\s*WORLDEDIT\s*$", re.IGNORECASE)
_VANILLA_HEADER = re.compile(r"^#\s*VANILLA\s*$", re.IGNORECASE)


class Builder:
    """Reads commands.txt and executes them via RCON (vanilla) and bridge (WorldEdit)."""

    def __init__(
        self,
        bridge_url: str = BRIDGE_URL,
        rcon_host: str = RCON_HOST,
        rcon_port: int = RCON_PORT,
        rcon_password: str = RCON_PASSWORD,
    ) -> None:
        self.bridge_url = bridge_url.rstrip("/")
        self._rcon_host = rcon_host
        self._rcon_port = rcon_port
        self._rcon_password = rcon_password
        self._rcon: RconClient | None = None

    # ── Command parsing ────────────────────────────────────────────────────────

    def _parse_commands(self, path: Path) -> list[tuple[str, str]]:
        """Return (channel, command) pairs from commands.txt.

        channel: "rcon" (default) | "bridge" (WorldEdit)
        Skips blank lines and comment lines.
        """
        channel = "rcon"
        result: list[tuple[str, str]] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _WORLDEDIT_HEADER.match(line):
                channel = "bridge"
                continue
            if _VANILLA_HEADER.match(line):
                channel = "rcon"
                continue
            if line.startswith("#"):
                continue  # skip other comments
            result.append((channel, line))
        return result

    # ── Execution ─────────────────────────────────────────────────────────────

    def _run_commands(self, commands: list[tuple[str, str]]) -> dict:
        """Execute all commands and return a log dict."""
        log: dict = {
            "commands_total": len(commands),
            "commands_ok": 0,
            "commands_failed": 0,
            "blocks_changed": 0,
            "errors": [],
        }
        start = time.monotonic()

        for channel, cmd in commands:
            try:
                if channel == "bridge":
                    self._send_bridge(cmd)
                    log["commands_ok"] += 1
                    time.sleep(BRIDGE_DELAY)
                else:
                    resp = self._send_rcon(cmd)
                    log["blocks_changed"] += self._count_changed(resp)
                    log["commands_ok"] += 1
                    time.sleep(VANILLA_DELAY)
            except Exception as exc:  # noqa: BLE001
                log["commands_failed"] += 1
                log["errors"].append({"command": cmd, "error": str(exc)})

        log["execution_time_s"] = round(time.monotonic() - start, 2)
        return log

    # ── RCON helpers ──────────────────────────────────────────────────────────

    def _send_rcon(self, cmd: str) -> str:
        """Send command via RCON, raise on error response."""
        if self._rcon is None:
            raise RuntimeError("RCON client not initialized")
        resp = self._rcon.command(cmd)
        if self._is_error(resp):
            raise RuntimeError(f"RCON error response: {resp!r}")
        return resp

    def _is_error(self, response: str) -> bool:
        """Return True if response indicates a command error (not benign)."""
        if any(p.search(response) for p in _BENIGN_PATTERNS):
            return False
        return any(p.search(response) for p in _ERROR_PATTERNS)

    def _count_changed(self, response: str) -> int:
        """Extract block change count from RCON response."""
        m = _CHANGED_RE.search(response)
        return int(m.group(1)) if m else 0

    def _close_rcon(self) -> None:
        if self._rcon is not None:
            try:
                self._rcon.close()
            except Exception:  # noqa: BLE001
                pass
            self._rcon = None

    # ── Bridge helpers ────────────────────────────────────────────────────────

    def _send_bridge(self, cmd: str) -> dict:
        """POST /command to Mineflayer bridge."""
        r = requests.post(
            f"{self.bridge_url}/command",
            json={"command": cmd},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    # ── Forceload ─────────────────────────────────────────────────────────────

    def _forceload(self, x1: int, z1: int, x2: int, z2: int, action: str) -> None:
        """Add or remove a forceloaded chunk region via RCON."""
        if self._rcon is None:
            return
        try:
            self._rcon.command(f"forceload {action} {x1} {z1} {x2} {z2}")
        except Exception:  # noqa: BLE001
            pass  # forceload failures are non-fatal



# ── CLI entry ─────────────────────────────────────────────────────────────────

def _parse_origin(value: str) -> tuple[int, int, int]:
    parts = value.split(",")
    if len(parts) != 3:
        raise ValueError(f"origin must be x,y,z — got: {value!r}")
    return (int(parts[0].strip()), int(parts[1].strip()), int(parts[2].strip()))


def _parse_size(value: str) -> tuple[int, int, int]:
    parts = value.lower().replace("x", ",").split(",")
    if len(parts) != 3:
        raise ValueError(f"size must be WxHxL — got: {value!r}")
    return (int(parts[0].strip()), int(parts[1].strip()), int(parts[2].strip()))


def run_from_cli(
    workspace_dir: Path,
    origin: tuple[int, int, int],
    size: tuple[int, int, int],
    bridge_url: str = BRIDGE_URL,
    rcon_host: str = RCON_HOST,
    rcon_port: int = RCON_PORT,
    rcon_password: str = RCON_PASSWORD,
) -> dict:
    """Run builder from CLI arguments (no SessionState dependency)."""
    builder = Builder(
        bridge_url=bridge_url,
        rcon_host=rcon_host,
        rcon_port=rcon_port,
        rcon_password=rcon_password,
    )

    # Preflight — check commands.txt and bridge
    commands_path = workspace_dir / "commands.txt"
    if not commands_path.exists():
        print("Error: commands.txt not found", file=sys.stderr)
        sys.exit(1)

    try:
        r = requests.get(f"{bridge_url.rstrip('/')}/status", timeout=5)
        r.raise_for_status()
        if not r.json().get("connected"):
            print("Error: Mineflayer bot not connected", file=sys.stderr)
            sys.exit(1)
    except requests.RequestException as exc:
        print(f"Error: Cannot reach bridge at {bridge_url}: {exc}", file=sys.stderr)
        sys.exit(1)

    # Connect RCON
    builder._rcon = RconClient(rcon_host, rcon_port, rcon_password)

    # Parse and execute
    commands = builder._parse_commands(commands_path)
    ox, oy, oz = origin
    wx, _, wz = size
    builder._forceload(ox, oz, ox + wx, oz + wz, "add")

    try:
        log = builder._run_commands(commands)
    finally:
        builder._forceload(ox, oz, ox + wx, oz + wz, "remove")
        builder._close_rcon()

    # Write output
    log["session_id"] = workspace_dir.name
    (workspace_dir / "build_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    (workspace_dir / "builder_done.json").write_text(
        json.dumps({"status": "DONE", "commands_ok": log["commands_ok"]}), encoding="utf-8"
    )
    return log


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        prog="kasukabe.builder",
        description="Execute Minecraft build commands from commands.txt.",
    )
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    parser.add_argument("--origin", required=True, help="Build origin x,y,z")
    parser.add_argument("--size", required=True, help="Build size WxHxL")
    parser.add_argument("--bridge-url", default=BRIDGE_URL)
    parser.add_argument("--rcon-host", default=RCON_HOST)
    parser.add_argument("--rcon-port", type=int, default=RCON_PORT)
    parser.add_argument("--rcon-password", default=RCON_PASSWORD)

    args = parser.parse_args()
    origin = _parse_origin(args.origin)
    size = _parse_size(args.size)

    log = run_from_cli(
        workspace_dir=Path(args.workspace),
        origin=origin,
        size=size,
        bridge_url=args.bridge_url,
        rcon_host=args.rcon_host,
        rcon_port=args.rcon_port,
        rcon_password=args.rcon_password,
    )

    print(f"Build done: {log['commands_ok']} ok, {log['commands_failed']} failed")


if __name__ == "__main__":
    main()
