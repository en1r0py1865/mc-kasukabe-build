"""Smoke tests — verify core logic without external dependencies."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from kasukabe.agents.builder import _CHANGED_RE, _ERROR_PATTERNS, _VANILLA_HEADER, _WORLDEDIT_HEADER
from kasukabe.agents.builder import Builder
from kasukabe.bridge_client import BridgeClient
from kasukabe.models import BlockOp


# ── Model tests ───────────────────────────────────────────────────────────────

class TestBlockOp:
    def test_creation(self):
        b = BlockOp(x=5, y=3, z=7, block="minecraft:oak_planks")
        assert b.x == 5
        assert b.block == "minecraft:oak_planks"


# ── Builder parsing tests ─────────────────────────────────────────────────────

class TestBuilderParsing:
    def _make_builder(self) -> Builder:
        return Builder()

    def test_parse_vanilla_only(self, tmp_path):
        commands_txt = tmp_path / "commands.txt"
        commands_txt.write_text(
            "# VANILLA\nfill 100 64 200 110 64 210 minecraft:stone\nsetblock 105 65 205 minecraft:air\n"
        )
        b = self._make_builder()
        parsed = b._parse_commands(commands_txt)
        assert len(parsed) == 2
        assert all(ch == "rcon" for ch, _ in parsed)
        assert parsed[0][1] == "fill 100 64 200 110 64 210 minecraft:stone"

    def test_parse_worldedit_section(self, tmp_path):
        commands_txt = tmp_path / "commands.txt"
        commands_txt.write_text(
            "# VANILLA\nfill 100 64 200 110 64 200 minecraft:stone\n# WORLDEDIT\n//set minecraft:oak_planks\n"
        )
        b = self._make_builder()
        parsed = b._parse_commands(commands_txt)
        assert parsed[0] == ("rcon", "fill 100 64 200 110 64 200 minecraft:stone")
        assert parsed[1] == ("bridge", "//set minecraft:oak_planks")

    def test_parse_skips_blank_and_comments(self, tmp_path):
        commands_txt = tmp_path / "commands.txt"
        commands_txt.write_text("# comment\n\nsetblock 1 2 3 minecraft:stone\n")
        b = self._make_builder()
        parsed = b._parse_commands(commands_txt)
        assert len(parsed) == 1

    def test_default_channel_is_rcon(self, tmp_path):
        commands_txt = tmp_path / "commands.txt"
        commands_txt.write_text("setblock 1 2 3 minecraft:stone\n")
        b = self._make_builder()
        parsed = b._parse_commands(commands_txt)
        assert parsed[0][0] == "rcon"


class TestBuilderRegex:
    def test_changed_re_fill(self):
        m = _CHANGED_RE.search("Changed 64 blocks in (...).")
        assert m is not None
        assert m.group(1) == "64"

    def test_changed_re_filled(self):
        m = _CHANGED_RE.search("Successfully filled 128 blocks")
        assert m is not None
        assert m.group(1) == "128"

    def test_changed_re_no_match(self):
        assert _CHANGED_RE.search("Command ran successfully") is None

    def test_error_patterns_unknown_command(self):
        assert any(p.search("Unknown command: fill") for p in _ERROR_PATTERNS)

    def test_error_patterns_invalid(self):
        assert any(p.search("Invalid block type: foo") for p in _ERROR_PATTERNS)

    def test_worldedit_header(self):
        assert _WORLDEDIT_HEADER.match("# WORLDEDIT")
        assert _WORLDEDIT_HEADER.match("# worldedit")
        assert not _WORLDEDIT_HEADER.match("setblock 1 2 3 minecraft:stone")

    def test_vanilla_header(self):
        assert _VANILLA_HEADER.match("# VANILLA")
        assert _VANILLA_HEADER.match("#VANILLA")


# ── BridgeClient URL construction ─────────────────────────────────────────────

class TestBridgeClient:
    def test_base_url_trailing_slash_stripped(self):
        c = BridgeClient("http://localhost:3001/")
        assert c.base_url == "http://localhost:3001"

    def test_get_block_url(self):
        c = BridgeClient("http://localhost:3001")
        expected = "http://localhost:3001/block/100/64/200"
        assert f"{c.base_url}/block/100/64/200" == expected

    def test_is_connected_false_on_connection_error(self):
        c = BridgeClient("http://localhost:19999")
        assert c.is_connected() is False


# ── CLI entry tests ───────────────────────────────────────────────────────────

class TestBuilderCLI:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, "-m", "kasukabe.agents.builder", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--workspace" in result.stdout


class TestVideoProcessorCLI:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, "-m", "kasukabe.video_processor", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--input" in result.stdout
