"""Smoke tests — verify core logic without external dependencies."""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kasukabe.agents.builder import _CHANGED_RE, _ERROR_PATTERNS, _VANILLA_HEADER, _WORLDEDIT_HEADER
from kasukabe.agents.builder import Builder
from kasukabe.bridge_client import BridgeClient
from kasukabe.models import BlockOp, PipelineBlocked, SessionState
from kasukabe.video_processor import VideoProcessingError


# ── Model tests ───────────────────────────────────────────────────────────────

class TestSessionState:
    def test_defaults(self):
        s = SessionState(
            session_id="abc123",
            input_path="test.jpg",
            origin=(100, 64, 200),
            size=(10, 8, 10),
        )
        assert s.iteration == 0
        assert s.phase == "INIT"
        assert s.completion_rate == 0.0
        assert s.failure_reason == ""

    def test_phase_transitions(self):
        s = SessionState("x", "y", (0, 0, 0), (0, 0, 0))
        s.phase = "ARCHITECT"
        assert s.phase == "ARCHITECT"


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
        # Verify the URL would be constructed correctly
        expected = "http://localhost:3001/block/100/64/200"
        assert f"{c.base_url}/block/100/64/200" == expected

    def test_is_connected_false_on_connection_error(self):
        c = BridgeClient("http://localhost:19999")  # nothing listening here
        assert c.is_connected() is False


# ── Foreman helpers ────────────────────────────────────────────────────────────

class TestForemanHelpers:
    def test_is_video(self, tmp_path):
        from kasukabe.foreman import Foreman
        f = Foreman(workspace_root=tmp_path)
        assert f._is_video("clip.mp4") is True
        assert f._is_video("clip.MOV") is True
        assert f._is_video("photo.jpg") is False
        assert f._is_video("photo.PNG") is False

    def test_read_completion_rate_missing_file(self, tmp_path):
        from kasukabe.foreman import Foreman
        from kasukabe.models import SessionState
        f = Foreman(workspace_root=tmp_path)
        s = SessionState("x", "y", (0, 0, 0), (0, 0, 0), workspace_dir=tmp_path)
        assert f._read_completion_rate(s) == 0.0

    def test_read_completion_rate_from_file(self, tmp_path):
        from kasukabe.foreman import Foreman
        from kasukabe.models import SessionState
        (tmp_path / "diff_report.json").write_text(json.dumps({"completion_rate": 0.92}))
        f = Foreman(workspace_root=tmp_path)
        s = SessionState("x", "y", (0, 0, 0), (0, 0, 0), workspace_dir=tmp_path)
        assert f._read_completion_rate(s) == 0.92


# ── Architect JSON parsing ────────────────────────────────────────────────────

class TestArchitectJsonParsing:
    def test_parse_clean_json(self):
        from kasukabe.agents.architect import Architect
        a = Architect.__new__(Architect)
        result = a._parse_json('{"meta": {}, "materials": [], "layers": [], "blocks": []}')
        assert result is not None
        assert "meta" in result

    def test_parse_fenced_json(self):
        from kasukabe.agents.architect import Architect
        a = Architect.__new__(Architect)
        fenced = '```json\n{"meta": {}, "materials": [], "layers": [], "blocks": []}\n```'
        result = a._parse_json(fenced)
        assert result is not None

    def test_parse_invalid_returns_none(self):
        from kasukabe.agents.architect import Architect
        a = Architect.__new__(Architect)
        assert a._parse_json("not json at all") is None

    def test_is_valid_blueprint_missing_key(self):
        from kasukabe.agents.architect import Architect
        a = Architect.__new__(Architect)
        assert not a._is_valid_blueprint({"meta": {}, "materials": []})  # missing layers, blocks

    def test_is_valid_blueprint_ok(self):
        from kasukabe.agents.architect import Architect
        a = Architect.__new__(Architect)
        bp = {
            "meta": {}, "materials": [{"block": "minecraft:stone"}],
            "layers": [], "blocks": []
        }
        assert a._is_valid_blueprint(bp)
