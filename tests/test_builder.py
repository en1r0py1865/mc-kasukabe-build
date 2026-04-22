"""Tests for kasukabe.agents.builder command routing."""
from __future__ import annotations

from pathlib import Path

import pytest

from kasukabe.agents.builder import Builder


class FakeRcon:
    def __init__(self, responses: dict[str, str] | None = None,
                 default: str = "Changed 1 block"):
        self.responses = responses or {}
        self.default = default
        self.commands: list[str] = []

    def command(self, cmd: str) -> str:
        self.commands.append(cmd)
        for needle, resp in self.responses.items():
            if needle in cmd:
                return resp
        return self.default

    def close(self) -> None:
        pass


@pytest.fixture
def commands_file(tmp_path: Path) -> Path:
    """commands.txt with one WORLDEDIT section and one VANILLA section."""
    p = tmp_path / "commands.txt"
    p.write_text(
        "# WORLDEDIT\n"
        "//schem load build\n"
        "//paste\n"
        "# VANILLA\n"
        "setblock 100 64 200 minecraft:stone\n",
        encoding="utf-8",
    )
    return p


class TestRunCommandsRoutesWorldEditViaBridge:
    def test_worldedit_commands_executed_via_bridge(self, commands_file, monkeypatch):
        fake = FakeRcon()
        b = Builder()
        b._rcon = fake
        bridge_calls: list[str] = []
        monkeypatch.setattr(
            b,
            "_send_bridge",
            lambda cmd: bridge_calls.append(cmd) or {"executed": f"/{cmd}"},
        )

        commands = b._parse_commands(commands_file)
        log = b._run_commands(commands)

        assert bridge_calls == ["//schem load build", "//paste"]
        assert len(fake.commands) == 1
        assert any("setblock" in c for c in fake.commands)
        assert log["commands_ok"] == 3
        assert log["commands_failed"] == 0

    def test_vanilla_permission_denied_recorded_as_failure(self, commands_file):
        """A vanilla command hitting a permission gate must be classified
        as failure. NOTE: FAWE-command permission errors are NOT testable
        here because FAWE output is invisible to RCON — FAWE routes its
        messages to the player chat packet, not RCON's reply stream. See
        Builder._run_commands docstring."""
        fake = FakeRcon(responses={
            "setblock": "You don't have permission to do that.",
        })
        b = Builder()
        b._rcon = fake
        b._send_bridge = lambda cmd: {"executed": f"/{cmd}"}
        commands = b._parse_commands(commands_file)
        log = b._run_commands(commands)

        assert log["commands_failed"] == 1
        assert "permission" in log["errors"][0]["error"].lower()

    def test_unknown_command_recorded_as_failure(self, commands_file):
        """Vanilla command parser failures from RCON must still surface."""
        fake = FakeRcon(responses={
            "setblock": "Unknown or incomplete command, see below for error",
        })
        b = Builder()
        b._rcon = fake
        b._send_bridge = lambda cmd: {"executed": f"/{cmd}"}
        commands = b._parse_commands(commands_file)
        log = b._run_commands(commands)

        assert log["commands_failed"] == 1
        assert "unknown" in log["errors"][0]["error"].lower()

    def test_tp_in_worldedit_section_routed_via_bridge(self, tmp_path):
        """A `/tp @s ...` line inside `# WORLDEDIT` must go via bridge (bot.chat),
        not RCON — RCON-side /tp would teleport the console, not the bot, so
        the subsequent //paste would still land at the bot's spawn position.
        See minecraft_context FAWE pitfalls #1 and #3."""
        p = tmp_path / "commands.txt"
        p.write_text(
            "# WORLDEDIT\n/tp @s 900 10 200\n//paste\n",
            encoding="utf-8",
        )
        fake = FakeRcon()
        b = Builder()
        b._rcon = fake
        bridge_calls: list[str] = []
        b._send_bridge = lambda cmd: bridge_calls.append(cmd) or {"executed": f"/{cmd}"}
        commands = b._parse_commands(p)
        log = b._run_commands(commands)

        assert bridge_calls == ["/tp @s 900 10 200", "//paste"]
        assert fake.commands == []           # RCON untouched
        assert log["commands_ok"] == 2

    def test_full_worldedit_sequence_via_bridge(self, tmp_path, monkeypatch):
        """/tp @s + //schem load + //paste all route to bridge in order, with
        BRIDGE_SCHEM_LOAD_DELAY applied after //schem load only. This is the
        regression gate for the whole paste chain — any single mis-routing
        or a missing post-load delay loses the mural (see minecraft_context
        FAWE pitfalls #1 and #4)."""
        p = tmp_path / "commands.txt"
        p.write_text(
            "# WORLDEDIT\n/tp @s 900 10 200\n//schem load build\n//paste\n",
            encoding="utf-8",
        )
        fake = FakeRcon()
        b = Builder()
        b._rcon = fake
        bridge_calls: list[str] = []
        b._send_bridge = lambda cmd: bridge_calls.append(cmd) or {"executed": f"/{cmd}"}
        sleeps: list[float] = []
        monkeypatch.setattr(
            "kasukabe.agents.builder.time.sleep",
            lambda s: sleeps.append(s),
        )

        commands = b._parse_commands(p)
        log = b._run_commands(commands)

        assert bridge_calls == [
            "/tp @s 900 10 200",
            "//schem load build",
            "//paste",
        ]
        assert fake.commands == []            # RCON untouched
        assert log["commands_ok"] == 3
        assert log["commands_failed"] == 0
        from kasukabe.agents.builder import BRIDGE_DELAY, BRIDGE_SCHEM_LOAD_DELAY
        assert sleeps == [BRIDGE_DELAY, BRIDGE_SCHEM_LOAD_DELAY, BRIDGE_DELAY]


class TestParseCommands:
    def test_channels_tagged_correctly(self, commands_file):
        b = Builder()
        parsed = b._parse_commands(commands_file)
        assert parsed[0] == ("bridge", "//schem load build")
        assert parsed[-1] == ("rcon", "setblock 100 64 200 minecraft:stone")
