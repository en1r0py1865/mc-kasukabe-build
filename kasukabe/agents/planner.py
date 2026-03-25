"""Planner agent — converts blueprint.json into Minecraft build commands."""
from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic

from kasukabe.models import PipelineBlocked, SessionState

PLANNER_SYSTEM_PROMPT = """You are a Minecraft building command planner. Your job is to read a \
blueprint JSON and generate an ordered sequence of Minecraft commands to construct it.

You have two tools available:
- read_blueprint: Read the blueprint for this session
- write_commands: Write the final command list to the workspace

Command generation rules:
1. ALWAYS start by clearing the build zone: fill ox oy oz (ox+W-1) (oy+H-1) (oz+L-1) minecraft:air
2. Build bottom-up: process layers from y_offset=0 upward
3. For solid rectangular fills: use /fill x1 y1 z1 x2 y2 z2 block  (NO leading slash in commands.txt)
4. For single blocks or irregular shapes: use setblock x y z block
5. For large solid areas (> 100 blocks): use WorldEdit //set instead of many /fill commands
6. ALL coordinates must be ABSOLUTE (origin.x + rel_x, origin.y + rel_y, origin.z + rel_z)
7. No relative coordinates (~)

Output format for commands.txt — use these EXACT section headers:
# VANILLA
fill 100 64 200 109 64 209 minecraft:stone
setblock 104 67 204 minecraft:glass_pane
# WORLDEDIT
//pos1 100 65 200
//pos2 109 69 209
//set minecraft:oak_log

When fix_commands are provided, include them FIRST in the # VANILLA section before new commands.
Call write_commands exactly once when done.
"""

_TOOLS: list[dict] = [
    {
        "name": "read_blueprint",
        "description": "Read the building blueprint JSON for this session",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"}
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "write_commands",
        "description": (
            "Write the final commands.txt to the workspace. "
            "Call exactly once with all commands in order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Ordered list of command lines. Include section headers "
                        "('# VANILLA', '# WORLDEDIT') and blank lines as separate entries."
                    ),
                },
            },
            "required": ["session_id", "commands"],
        },
    },
]


class Planner:
    """Converts blueprint.json into an executable command sequence."""

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-5"):
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model

    def plan(self, session: SessionState, fix_commands: list[str] | None = None) -> None:
        """Run the planner tool-use loop until write_commands is called.

        Args:
            session: Current session state.
            fix_commands: Commands from Inspector diff_report to prepend (iteration > 1).

        Raises:
            PipelineBlocked: If write_commands is never called after max turns.
        """
        user_msg = f"Plan the construction for session {session.session_id}."
        if fix_commands:
            user_msg += (
                f"\n\nIMPORTANT — include these fix commands from the previous build iteration "
                f"FIRST in the # VANILLA section:\n"
                + "\n".join(fix_commands)
            )

        messages: list[dict] = [{"role": "user", "content": user_msg}]
        max_turns = 12  # prevent infinite loops

        for turn in range(max_turns):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=PLANNER_SYSTEM_PROMPT,
                tools=_TOOLS,
                messages=messages,
            )

            if response.stop_reason == "end_turn":
                # Model finished without calling write_commands — treat as error
                break

            if response.stop_reason == "tool_use":
                tool_results: list[dict] = []
                finished = False

                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    result_content = self._handle_tool(block.name, block.input, session)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_content,
                    })
                    if block.name == "write_commands":
                        finished = True  # commands written, we're done

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

                if finished:
                    self._write_done(session)
                    return

        raise PipelineBlocked(
            f"Planner: write_commands was not called after {max_turns} turns. "
            "Check the model response for errors."
        )

    def _handle_tool(self, name: str, tool_input: dict, session: SessionState) -> str:
        """Execute a tool call and return the result as a JSON string."""
        if name == "read_blueprint":
            bp_path = session.workspace_dir / "blueprint.json"
            if not bp_path.exists():
                return json.dumps({"error": "blueprint.json not found — run Architect first"})
            return bp_path.read_text(encoding="utf-8")

        if name == "write_commands":
            commands: list[str] = tool_input.get("commands", [])
            if not commands:
                return json.dumps({"error": "commands list is empty"})
            content = "\n".join(commands)
            out_path = session.workspace_dir / "commands.txt"
            out_path.write_text(content, encoding="utf-8")
            non_comment = [
                c for c in commands if c.strip() and not c.strip().startswith("#")
            ]
            return json.dumps({"status": "written", "total_lines": len(commands),
                                "command_count": len(non_comment)})

        return json.dumps({"error": f"unknown tool: {name}"})

    def _write_done(self, session: SessionState) -> None:
        """Write planner_done.json after successful command generation."""
        commands_path = session.workspace_dir / "commands.txt"
        cmd_count = 0
        if commands_path.exists():
            lines = commands_path.read_text(encoding="utf-8").splitlines()
            cmd_count = sum(
                1 for ln in lines if ln.strip() and not ln.strip().startswith("#")
            )
        (session.workspace_dir / "planner_done.json").write_text(
            json.dumps({"status": "DONE", "command_count": cmd_count}),
            encoding="utf-8",
        )
