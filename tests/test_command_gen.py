"""Tests for kasukabe.command_gen — blueprint → .schem + commands.txt."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _write_blueprint(workspace: Path, extra_blocks: list[dict] | None = None) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    blocks = [
        {"x": 0, "y": 0, "z": 0, "block": "minecraft:white_concrete"},
        {"x": 1, "y": 0, "z": 0, "block": "minecraft:oak_log[axis=y]"},
        {"x": 0, "y": 1, "z": 0, "block": "minecraft:oak_log[axis=x]"},
        {"x": 1, "y": 1, "z": 0, "block": "minecraft:stone"},
    ]
    if extra_blocks:
        blocks.extend(extra_blocks)
    bp = {
        "meta": {
            "name": "test_mural",
            "size": {"x": 2, "y": 2, "z": 1},
            "origin": {"x": 100, "y": 64, "z": 200},
            "axis": "xy",
            "view_face": "side",
            "actual_footprint": {"w": 2, "h": 2},
            "deterministic": True,
        },
        "materials": [],
        "layers": [],
        "blocks": blocks,
    }
    (workspace / "blueprint.json").write_text(json.dumps(bp))
    return bp


def _run(workspace: Path, *extra: str) -> dict:
    cmd = [sys.executable, "-m", "kasukabe.command_gen", "--workspace", str(workspace), *extra]
    subprocess.run(cmd, capture_output=True)
    done = workspace / "command_gen_done.json"
    assert done.is_file()
    return json.loads(done.read_text())


class TestFullMode:
    def test_produces_schem_and_worldedit_commands(self, tmp_path):
        _write_blueprint(tmp_path)
        result = _run(tmp_path)
        assert result["status"] == "DONE"
        assert result["mode"] == "schematic"
        assert (tmp_path / "build.schem").is_file()
        assert (tmp_path / "build.schem").stat().st_size > 0
        text = (tmp_path / "commands.txt").read_text()
        assert text.startswith("# WORLDEDIT")
        assert "/tp @s 100 64 200" in text
        assert "//schem load build" in text
        assert "//paste" in text
        assert "//pos1" not in text              # dead-code regression guard
        assert "-o" not in text   # plan §5: -o removed
        assert "/execute positioned" not in text

    def test_worldedit_tp_precedes_paste(self, tmp_path):
        """Bot must teleport to origin BEFORE //paste, or the mural lands at
        the bot's spawn position (see minecraft_context FAWE pitfall #1)."""
        _write_blueprint(tmp_path)
        _run(tmp_path)
        lines = (tmp_path / "commands.txt").read_text().splitlines()
        tp_idx = next(i for i, l in enumerate(lines) if l.startswith("/tp @s"))
        paste_idx = next(i for i, l in enumerate(lines) if l.strip() == "//paste")
        assert tp_idx < paste_idx

    def test_block_states_are_preserved_in_schem(self, tmp_path):
        _write_blueprint(tmp_path)
        _run(tmp_path)
        # mcschematic writes Sponge v2; easiest sanity check: round-trip via nbtlib.
        pytest.importorskip("nbtlib")
        import nbtlib
        f = nbtlib.load(tmp_path / "build.schem", gzipped=True)
        # Sponge v2 stores the palette at Schematic.Palette or at root.Palette depending on
        # mcschematic version. Search for "oak_log[axis=x]" and "oak_log[axis=y]" in the
        # serialised bytes as a simple containment check.
        raw = (tmp_path / "build.schem").read_bytes()
        # .schem is gzipped NBT — decompress first
        import gzip
        decompressed = gzip.decompress(raw)
        assert b"oak_log[axis=y]" in decompressed
        assert b"oak_log[axis=x]" in decompressed


class TestRegionMode:
    def test_produces_vanilla_only_no_schem(self, tmp_path):
        _write_blueprint(tmp_path)
        result = _run(tmp_path, "--region", "0,0,2,2")
        assert result["status"] == "DONE"
        assert result["mode"] == "region_vanilla"
        assert not (tmp_path / "build.schem").is_file()
        text = (tmp_path / "commands.txt").read_text()
        assert text.startswith("# VANILLA")
        assert "# WORLDEDIT" not in text
        # Every block in the bp is inside the region, so all 4 setblocks emitted
        assert text.count("setblock") == 4

    def test_absolute_coords_have_origin_applied(self, tmp_path):
        _write_blueprint(tmp_path)
        _run(tmp_path, "--region", "0,0,2,2")
        lines = (tmp_path / "commands.txt").read_text().splitlines()
        # origin=(100, 64, 200), blueprint coord (0, 0, 0) → world (100, 64, 200)
        assert any("100 64 200 minecraft:white_concrete" in l for l in lines) or any(
            "100 65 200 minecraft:oak_log[axis=x]" in l for l in lines
        )


class TestRegionExcludesExtras:
    def test_region_vanilla_excludes_glowstone_and_backdrop(self, tmp_path):
        """Region filter must drop backlight/backdrop extras from VANILLA output."""
        _write_blueprint(tmp_path, extra_blocks=[
            # Simulated glowstone_row (z=0, y outside main plane)
            {"x": 0, "y": -1, "z": 0, "block": "minecraft:glowstone"},
            {"x": 0, "y": 2,  "z": 0, "block": "minecraft:glowstone"},
            # Simulated backdrop (z=1, one behind the main plane)
            {"x": 0, "y": 0,  "z": 1, "block": "minecraft:red_concrete"},
        ])
        # Mark the blueprint as glowstone_row so actual_footprint.h reflects +2
        bp_path = tmp_path / "blueprint.json"
        data = json.loads(bp_path.read_text())
        data["meta"]["backlight"] = "glowstone_row"
        data["meta"]["actual_footprint"] = {"w": 2, "h": 4}  # main 2×2 + 2 rows
        bp_path.write_text(json.dumps(data))

        _run(tmp_path, "--region", "0,0,2,2")
        text = (tmp_path / "commands.txt").read_text()
        assert "glowstone" not in text, "glowstone extras leaked into region VANILLA"
        assert "red_concrete" not in text, "backdrop leaked into region VANILLA"


class TestLightBlock:
    def test_light_blocks_included_when_present_in_blueprint(self, tmp_path):
        # The pixel_replica injects light_block entries; command_gen just serialises
        # whatever is in blueprint.json. Verify light_block survives the round-trip.
        _write_blueprint(tmp_path, extra_blocks=[
            {"x": 1, "y": 1, "z": 1, "block": "minecraft:light[level=15]"},
        ])
        _run(tmp_path)
        import gzip
        decompressed = gzip.decompress((tmp_path / "build.schem").read_bytes())
        # FAWE/mcschematic maps "light" to "light" (modern block name)
        assert b"light" in decompressed
