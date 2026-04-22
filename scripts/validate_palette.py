"""Validate BLOCK_PALETTE against Minecraft 1.21.x block registry.

Two modes:
  --offline (default): download + cache PrismarineJS/minecraft-data blocks.json
                       diff palette block_ids against registry.
  --online            : query bridge /validate_block endpoint per block.
                       Useful to verify your running Paper server accepts these IDs.

Usage:
    python scripts/validate_palette.py [--offline|--online] [--version 1.21.4] [--refresh]
Exit code 1 if any unknown block_ids are detected.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

# Ensure we can import kasukabe.* from repo root when invoked directly
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from kasukabe.block_palette import all_entries  # noqa: E402

# minecraft-data has data/pc/<VERSION>/blocks.json. 1.21.4 is the latest PC
# version currently published there; the palette targets 1.21.11 but the block
# registry is stable across 1.21.x bug-fix releases.
DEFAULT_VERSION = "1.21.4"
_CACHE_ROOT = Path.home() / ".cache" / "kasukabe" / "minecraft-data"
_RAW_URL = (
    "https://raw.githubusercontent.com/PrismarineJS/minecraft-data/master/"
    "data/pc/{version}/blocks.json"
)

_STATE_RE = re.compile(r"\[[^\]]*\]$")


def _strip_state(block_id: str) -> str:
    """`minecraft:oak_log[axis=y]` -> `minecraft:oak_log`."""
    return _STATE_RE.sub("", block_id)


def _fetch_registry(version: str, refresh: bool = False) -> set[str]:
    cache_file = _CACHE_ROOT / f"blocks_{version}.json"
    if cache_file.exists() and not refresh:
        data = json.loads(cache_file.read_text())
    else:
        url = _RAW_URL.format(version=version)
        print(f"[offline] fetching {url}")
        _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "kasukabe-validate"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
        cache_file.write_bytes(raw)
        data = json.loads(raw)
    return {f"minecraft:{b['name']}" for b in data}


def _run_offline(version: str, refresh: bool) -> int:
    registry = _fetch_registry(version, refresh=refresh)
    unknown: list[str] = []
    for entry in all_entries():
        base = _strip_state(entry.block_id)
        if base not in registry:
            unknown.append(entry.block_id)
    total = len(all_entries())
    print(f"[offline] palette entries: {total}, registry size: {len(registry)}")
    if unknown:
        print(f"[offline] UNKNOWN ({len(unknown)}):")
        for bid in unknown:
            print(f"  - {bid}")
        return 1
    print(f"[offline] OK — all {total} palette entries are valid for {version}")
    return 0


def _run_online() -> int:
    # Lazy import so --offline works without a running bridge dependency.
    from kasukabe.bridge_client import BridgeClient  # noqa: WPS433

    client = BridgeClient()
    if not client.is_connected():
        print("[online] bridge not reachable at KASUKABE_BRIDGE_URL; aborting")
        return 2
    unknown: list[str] = []
    for entry in all_entries():
        base = _strip_state(entry.block_id)
        try:
            ok = client.validate_block(base)
        except Exception as e:  # noqa: BLE001
            print(f"[online] error validating {base}: {e}")
            ok = False
        if not ok:
            unknown.append(entry.block_id)
    if unknown:
        print(f"[online] UNKNOWN ({len(unknown)}):")
        for bid in unknown:
            print(f"  - {bid}")
        return 1
    print(f"[online] OK — all {len(all_entries())} palette entries accepted by server")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="default: offline registry diff")
    mode.add_argument("--online", action="store_true", help="query bridge /validate_block")
    p.add_argument("--version", default=DEFAULT_VERSION, help=f"MC version (default {DEFAULT_VERSION})")
    p.add_argument("--refresh", action="store_true", help="bypass cache and re-download")
    args = p.parse_args()

    if args.online:
        return _run_online()
    return _run_offline(args.version, args.refresh)


if __name__ == "__main__":
    sys.exit(main())
