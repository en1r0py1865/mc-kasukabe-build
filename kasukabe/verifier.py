# kasukabe/verifier.py
"""Block verification — compares blueprint vs actual world state."""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

import os

import requests

from kasukabe.env import load_local_env
from kasukabe.rcon_client import RconClient

load_local_env()

BRIDGE_URL = os.getenv("KASUKABE_BRIDGE_URL", "http://localhost:3001")
RCON_HOST = os.getenv("CRAFTSMEN_RCON_HOST", "127.0.0.1")
RCON_PORT = int(os.getenv("CRAFTSMEN_RCON_PORT", "25575"))

MAX_SAMPLE = 200
RCON_SPOT_CHECK_LIMIT = 20

_DATA_GET_RE = re.compile(r"minecraft:(\w+)", re.IGNORECASE)


def _blueprint_to_absolute(
    blueprint: dict, origin: tuple[int, int, int]
) -> list[dict]:
    """Convert relative block coords to absolute world coords."""
    ox, oy, oz = origin
    return [
        {"x": b["x"] + ox, "y": b["y"] + oy, "z": b["z"] + oz, "block": b["block"]}
        for b in blueprint.get("blocks", [])
    ]


def _stratified_sample(blocks: list[dict], max_n: int) -> list[dict]:
    """Sample blocks evenly across y-layers."""
    if len(blocks) <= max_n:
        return list(blocks)

    by_y: dict[int, list[dict]] = {}
    for b in blocks:
        by_y.setdefault(b["y"], []).append(b)

    per_layer = max(1, max_n // len(by_y))
    sampled: list[dict] = []
    for layer_blocks in by_y.values():
        sampled.extend(random.sample(layer_blocks, min(per_layer, len(layer_blocks))))

    if len(sampled) > max_n:
        sampled = random.sample(sampled, max_n)

    return sampled


def _query_bridge_batch(
    sampled: list[dict], bridge_url: str = BRIDGE_URL
) -> list[dict]:
    """Query block states via bridge POST /blocks."""
    positions = [{"x": b["x"], "y": b["y"], "z": b["z"]} for b in sampled]
    results: list[dict] = []
    batch_size = 200

    for i in range(0, len(positions), batch_size):
        batch = positions[i : i + batch_size]
        try:
            r = requests.post(
                f"{bridge_url.rstrip('/')}/blocks",
                json={"positions": batch},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            results.extend(data.get("blocks", []))
        except Exception:
            results.extend(
                {"x": p["x"], "y": p["y"], "z": p["z"], "block": "unknown", "found": False}
                for p in batch
            )
    return results


def _parse_data_get_response(response: str) -> str | None:
    """Extract block ID from /data get block response."""
    m = _DATA_GET_RE.search(response)
    if m:
        return f"minecraft:{m.group(1).lower()}"
    return None


def _rcon_spot_check(
    sampled: list[dict],
    actual: list[dict],
    null_indices: list[int],
    rcon_host: str = RCON_HOST,
    rcon_port: int = RCON_PORT,
    rcon_password: str | None = None,
) -> None:
    """Fill in null bridge results using RCON /data get block."""
    rcon_password = rcon_password or os.getenv("CRAFTSMEN_RCON_PASSWORD", "")
    check_indices = null_indices[:RCON_SPOT_CHECK_LIMIT]
    try:
        rcon = RconClient(rcon_host, rcon_port, rcon_password)
    except Exception:
        return  # RCON unavailable, skip spot-check

    try:
        for idx in check_indices:
            b = sampled[idx]
            try:
                resp = rcon.command(f"data get block {b['x']} {b['y']} {b['z']}")
                block_id = _parse_data_get_response(resp)
                if block_id:
                    actual[idx] = {
                        "x": b["x"], "y": b["y"], "z": b["z"],
                        "block": block_id, "found": True,
                    }
                time.sleep(0.05)
            except Exception:
                pass
    finally:
        try:
            rcon.close()
        except Exception:
            pass


def _rcon_exact_match_check(
    sampled: list[dict],
    actual: list[dict],
    rcon_host: str = RCON_HOST,
    rcon_port: int = RCON_PORT,
    rcon_password: str | None = None,
) -> None:
    """Verify exact expected block matches via RCON execute-if-block checks."""
    rcon_password = rcon_password or os.getenv("CRAFTSMEN_RCON_PASSWORD", "")
    try:
        rcon = RconClient(rcon_host, rcon_port, rcon_password)
    except Exception:
        return

    try:
        for idx, expected in enumerate(sampled):
            try:
                resp = rcon.command(
                    f"execute if block {expected['x']} {expected['y']} {expected['z']} {expected['block']}"
                )
                if "Test passed" in resp:
                    actual[idx] = {
                        "x": expected["x"],
                        "y": expected["y"],
                        "z": expected["z"],
                        "block": expected["block"],
                        "found": True,
                    }
                time.sleep(0.02)
            except Exception:
                pass
    finally:
        try:
            rcon.close()
        except Exception:
            pass


def verify(
    workspace_dir: Path,
    origin: tuple[int, int, int],
    bridge_url: str = BRIDGE_URL,
    rcon_host: str = RCON_HOST,
    rcon_port: int = RCON_PORT,
    rcon_password: str | None = None,
) -> dict:
    """Verify build quality by comparing blueprint vs actual blocks.

    Writes verification_result.json to workspace_dir.

    Returns:
        Result dict with completion_rate, errors, etc.

    Raises:
        FileNotFoundError: If blueprint.json is missing.
    """
    bp_path = workspace_dir / "blueprint.json"
    if not bp_path.exists():
        raise FileNotFoundError(f"blueprint.json not found in {workspace_dir}")

    blueprint = json.loads(bp_path.read_text(encoding="utf-8"))
    expected = _blueprint_to_absolute(blueprint, origin)

    if not expected:
        result = {
            "completion_rate": 0.0,
            "total_blueprint_blocks": 0,
            "sampled_blocks": 0,
            "correct_blocks": 0,
            "errors": [],
        }
        (workspace_dir / "verification_result.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        return result

    sampled = _stratified_sample(expected, MAX_SAMPLE)
    actual = _query_bridge_batch(sampled, bridge_url)

    # RCON spot-check for nulls
    null_indices = [i for i, a in enumerate(actual) if not a.get("found")]
    if null_indices:
        pwd = rcon_password or os.getenv("CRAFTSMEN_RCON_PASSWORD", "")
        _rcon_spot_check(sampled, actual, null_indices, rcon_host, rcon_port, pwd)

    # Bridge reads can be wrong for far-away or unloaded chunks. Confirm exact matches via RCON.
    pwd = rcon_password or os.getenv("CRAFTSMEN_RCON_PASSWORD", "")
    _rcon_exact_match_check(sampled, actual, rcon_host, rcon_port, pwd)

    correct = sum(1 for a, e in zip(actual, sampled) if a.get("block") == e["block"])
    completion_rate = correct / len(sampled) if sampled else 0.0

    errors = [
        {
            "x": a.get("x", e["x"]),
            "y": a.get("y", e["y"]),
            "z": a.get("z", e["z"]),
            "expected": e["block"],
            "actual": a.get("block", "unknown"),
        }
        for a, e in zip(actual, sampled)
        if a.get("block") != e["block"]
    ]

    result = {
        "completion_rate": round(completion_rate, 4),
        "total_blueprint_blocks": len(expected),
        "sampled_blocks": len(sampled),
        "correct_blocks": correct,
        "error_count": len(errors),
        "errors": errors[:50],
    }

    (workspace_dir / "verification_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def _parse_origin(value: str) -> tuple[int, int, int]:
    parts = value.split(",")
    if len(parts) != 3:
        raise ValueError(f"origin must be x,y,z — got: {value!r}")
    return (int(parts[0].strip()), int(parts[1].strip()), int(parts[2].strip()))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kasukabe.verifier",
        description="Verify Minecraft build against blueprint.",
    )
    parser.add_argument("--workspace", required=True, help="Path to workspace directory")
    parser.add_argument("--origin", required=True, help="Build origin x,y,z")
    parser.add_argument("--bridge-url", default=BRIDGE_URL)
    parser.add_argument("--rcon-host", default=RCON_HOST)
    parser.add_argument("--rcon-port", type=int, default=RCON_PORT)
    parser.add_argument("--rcon-password", default=os.getenv("CRAFTSMEN_RCON_PASSWORD", ""))

    args = parser.parse_args()
    origin = _parse_origin(args.origin)

    result = verify(
        workspace_dir=Path(args.workspace),
        origin=origin,
        bridge_url=args.bridge_url,
        rcon_host=args.rcon_host,
        rcon_port=args.rcon_port,
        rcon_password=args.rcon_password,
    )

    rate = result["completion_rate"]
    print(f"Verification complete: {rate:.1%} ({result['correct_blocks']}/{result['sampled_blocks']})")
    sys.exit(0)


if __name__ == "__main__":
    main()
