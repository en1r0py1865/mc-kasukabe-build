"""Turn a pixel_replica blueprint into FAWE-ready placement commands.

Two output modes:

1. FULL (default):  produce  workspace/build.schem  +  workspace/commands.txt
   containing a 3-line # WORLDEDIT block that loads and pastes the schematic.

2. REGION (when --region is set in the blueprint meta OR --region flag is
   passed here): produce only a # VANILLA block with setblock commands for
   each block in the region. Does NOT build a schematic. Small area (<~500
   blocks) means FAWE's ~300 ms fixed overhead isn't worth paying.

Usage:
    python -m kasukabe.command_gen --workspace <DIR> [--region X1,Y1,X2,Y2]

Produces (under workspace):
    build.schem                  (full mode only)
    commands.txt                 (always)
    command_gen_done.json        (commit marker)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from pathlib import Path

import mcschematic

# Accept the latest version mcschematic knows; 1.21.x block registry is stable.
_SCHEM_VERSION = mcschematic.Version.JE_1_21_5


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _atomic_write_json(path: Path, obj) -> None:
    _atomic_write_bytes(path, json.dumps(obj, indent=2).encode("utf-8"))


def _build_schematic(blueprint: dict, out_dir: Path, name: str = "build") -> Path:
    """Write build.schem into out_dir, return the absolute path.

    mcschematic.save(folder, name, version) writes `<folder>/<name>.schem`.
    """
    schem = mcschematic.MCSchematic()
    for b in blueprint["blocks"]:
        schem.setBlock((int(b["x"]), int(b["y"]), int(b["z"])), b["block"])
    out_dir.mkdir(parents=True, exist_ok=True)
    # mcschematic writes directly; we perform an atomic move to preserve the
    # "last write is the commit" contract — save to tmp dir then os.replace.
    tmp_dir = out_dir / ".cmdgen_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    schem.save(str(tmp_dir), name, _SCHEM_VERSION)
    tmp_path = tmp_dir / f"{name}.schem"
    final_path = out_dir / f"{name}.schem"
    os.replace(tmp_path, final_path)
    try:
        tmp_dir.rmdir()
    except OSError:
        pass
    return final_path


def _vanilla_setblocks(blueprint: dict, region_filter=None) -> list[str]:
    """Return absolute-coord `setblock x y z block` lines.

    region_filter: optional callable(block_dict) -> bool; if provided, only
    blocks where it returns True are emitted.
    """
    origin = blueprint["meta"]["origin"]
    ox, oy, oz = int(origin["x"]), int(origin["y"]), int(origin["z"])
    out: list[str] = []
    for b in blueprint["blocks"]:
        if region_filter and not region_filter(b):
            continue
        x = ox + int(b["x"])
        y = oy + int(b["y"])
        z = oz + int(b["z"])
        out.append(f"setblock {x} {y} {z} {b['block']}")
    return out


def _region_filter_from_meta(blueprint: dict, region: tuple[int, int, int, int]):
    """Return a callable matching main-plane pixels inside image sub-rect (x1,y1,x2,y2).

    Excludes extras (backlight/backdrop/glowstone_row) by requiring the block
    to lie on the mural pixel plane (axis-dependent: xy→z==0, xz→y==0, yz→x==0).
    Backlight=glowstone_row inflates actual_footprint.h by 2; this filter
    reverses that offset so (u,v) mapping matches the main plane.
    """
    axis = blueprint["meta"].get("axis", "xy")
    fp = blueprint["meta"]["actual_footprint"]
    h_full = int(fp["h"])
    bl = blueprint["meta"].get("backlight", "none")
    h = h_full - 2 if bl == "glowstone_row" else h_full
    x1, y1, x2, y2 = region

    def _in_region(b: dict) -> bool:
        if axis == "xy":
            if b.get("z", 0) != 0:
                return False
            u, v = int(b["x"]), h - 1 - int(b["y"])
        elif axis == "xz":
            if b.get("y", 0) != 0:
                return False
            u, v = int(b["x"]), h - 1 - int(b["z"])
        else:  # yz
            if b.get("x", 0) != 0:
                return False
            u, v = int(b["z"]), h - 1 - int(b["y"])
        return (x1 <= u < x2) and (y1 <= v < y2)

    return _in_region


def _worldedit_block(origin: dict, name: str) -> str:
    """FAWE paste commands, routed through the Mineflayer bridge as bot.chat.

    `//paste` pastes the clipboard at the **player's current position** (the
    bot's). `//pos1` is ignored by paste — it only affects selection ops
    (`//set`, `//copy`, `//cut`, `//replace`). To land the mural at `origin`,
    the bot must first teleport itself there.

    We use `/tp @s` (self-teleport by the op'd bot) rather than bridge
    `/move` (mineflayer pathfinder) because `/tp` is instant, force-loads
    the target chunk, and cannot fail due to unreachable terrain.
    """
    ox, oy, oz = int(origin["x"]), int(origin["y"]), int(origin["z"])
    return (
        "# WORLDEDIT\n"
        f"/tp @s {ox} {oy} {oz}\n"
        f"//schem load {name}\n"
        "//paste\n"
    )


def _vanilla_block(lines: list[str]) -> str:
    return "# VANILLA\n" + "\n".join(lines) + ("\n" if lines else "")


def _run(args: argparse.Namespace, workspace: Path) -> dict:
    bp_path = workspace / "blueprint.json"
    if not bp_path.is_file():
        raise FileNotFoundError(f"missing {bp_path}")
    blueprint = json.loads(bp_path.read_text())

    meta = blueprint["meta"]
    origin = meta["origin"]

    # Decide mode --------------------------------------------------------
    region = None
    if args.region:
        m = re.match(r"^(\d+),(\d+),(\d+),(\d+)$", args.region)
        if not m:
            raise ValueError("--region must be X1,Y1,X2,Y2")
        region = tuple(int(v) for v in m.groups())

    mode = "region" if region else "full"

    commands_path = workspace / "commands.txt"

    if mode == "full":
        # Emit schematic + WORLDEDIT commands.
        schem_path = _build_schematic(blueprint, workspace, name="build")
        commands = _worldedit_block(origin, "build")
        _atomic_write_text(commands_path, commands)
        result = {
            "status": "DONE",
            "mode": "schematic",
            "block_count": len(blueprint["blocks"]),
            "schem_file": schem_path.name,
            "estimated_duration_s": 1,
        }
    else:  # region
        rfilter = _region_filter_from_meta(blueprint, region)
        lines = _vanilla_setblocks(blueprint, region_filter=rfilter)
        commands = _vanilla_block(lines)
        _atomic_write_text(commands_path, commands)
        result = {
            "status": "DONE",
            "mode": "region_vanilla",
            "block_count": len(lines),
            "region": list(region),
            "estimated_duration_s": max(1, int(len(lines) * 0.15)),
        }

    _atomic_write_json(workspace / "command_gen_done.json", result)
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", required=True)
    p.add_argument("--region", default="", help="X1,Y1,X2,Y2 — emits VANILLA setblock only")
    args = p.parse_args()

    workspace = Path(args.workspace)
    done_path = workspace / "command_gen_done.json"
    try:
        result = _run(args, workspace)
        print(f"[command_gen] DONE — mode={result['mode']} blocks={result['block_count']}")
        return 0
    except Exception as e:  # noqa: BLE001
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(done_path, {
                "status": "BLOCKED",
                "reason": str(e),
                "traceback": traceback.format_exc(),
            })
        except Exception:
            pass
        print(f"[command_gen] BLOCKED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
