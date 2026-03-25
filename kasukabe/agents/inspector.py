"""Inspector agent — verifies build quality and generates fix commands."""
from __future__ import annotations

import json
import os
import random
import re
import time
from pathlib import Path

import anthropic
import requests

from kasukabe.models import PipelineBlocked, SessionState
from kasukabe.rcon_client import RconClient

BRIDGE_URL = "http://localhost:3001"
RCON_HOST = "127.0.0.1"
RCON_PORT = 25575
RCON_PASSWORD = "minecraft123"

MAX_SAMPLE = 200  # max blocks to verify per inspection
RCON_SPOT_CHECK_LIMIT = 20  # max RCON fallback queries per inspection

INSPECTOR_SYSTEM_PROMPT = """You are a Minecraft build quality inspector. You receive:
1. The intended blueprint (what should be built)
2. A sample of block verification results comparing expected vs actual blocks
3. The computed completion_rate (0.0–1.0)

Diagnose the main issues and provide targeted fix commands.

Respond ONLY with valid JSON (no markdown):
{
  "diagnosis": "1-3 sentence technical description of what went wrong",
  "fix_commands": ["setblock X Y Z minecraft:block", "fill X1 Y1 Z1 X2 Y2 Z2 minecraft:block", ...],
  "should_continue": true
}

fix_commands rules:
- Use absolute world coordinates (not relative ~)
- Include only the top 20 most critical fixes (wrong block type or missing block)
- Commands are vanilla Minecraft format (setblock or fill, no leading slash)
- should_continue: true if fixes are needed, false if build looks complete
"""


class Inspector:
    """Verifies build quality by comparing blueprint vs actual world state."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-5",
        bridge_url: str = BRIDGE_URL,
        rcon_host: str = RCON_HOST,
        rcon_port: int = RCON_PORT,
        rcon_password: str = RCON_PASSWORD,
    ) -> None:
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model
        self.bridge_url = bridge_url.rstrip("/")
        self._rcon_host = rcon_host
        self._rcon_port = rcon_port
        self._rcon_password = rcon_password

    # ── Public interface ───────────────────────────────────────────────────────

    def inspect(self, session: SessionState) -> dict:
        """Compare blueprint vs world state, generate diff report.

        Returns:
            diff_report dict (also written to workspace_dir/diff_report.json).

        Raises:
            PipelineBlocked: If blueprint.json is missing.
        """
        blueprint = self._load_blueprint(session)
        expected = self._blueprint_to_absolute(blueprint, session.origin)

        if not expected:
            raise PipelineBlocked("Inspector: blueprint has no blocks to verify")

        # Stratified sample across layers
        sampled = self._stratified_sample(expected, MAX_SAMPLE)

        # Method A: batch bridge query
        actual = self._query_bridge_batch(sampled)

        # Method B: RCON spot-check for blocks bridge returned null (chunk not loaded)
        null_indices = [i for i, a in enumerate(actual) if not a.get("found")]
        if null_indices:
            rcon = self._connect_rcon()
            try:
                self._rcon_spot_check(sampled, actual, null_indices, rcon)
            finally:
                try:
                    rcon.close()
                except Exception:  # noqa: BLE001
                    pass

        # Compute completion rate
        correct = sum(
            1 for a, e in zip(actual, sampled)
            if a.get("block") == e["block"]
        )
        completion_rate = correct / len(sampled) if sampled else 0.0

        # Collect errors
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

        # LLM diagnosis
        diagnosis = self._llm_diagnose(blueprint, errors, completion_rate)

        report = {
            "session_id": session.session_id,
            "iteration": session.iteration,
            "total_blueprint_blocks": len(expected),
            "sampled_blocks": len(sampled),
            "correct_blocks": correct,
            "completion_rate": round(completion_rate, 4),
            "error_count": len(errors),
            "errors": errors[:50],  # cap stored errors at 50 for readability
            "diagnosis": diagnosis.get("diagnosis", ""),
            "fix_commands": diagnosis.get("fix_commands", []),
            "should_continue": diagnosis.get("should_continue", completion_rate < 0.85),
        }

        self._write_report(session, report)
        return report

    # ── Blueprint helpers ──────────────────────────────────────────────────────

    def _load_blueprint(self, session: SessionState) -> dict:
        bp_path = session.workspace_dir / "blueprint.json"
        if not bp_path.exists():
            raise PipelineBlocked("Inspector: blueprint.json not found")
        return json.loads(bp_path.read_text(encoding="utf-8"))

    def _blueprint_to_absolute(
        self, blueprint: dict, origin: tuple[int, int, int]
    ) -> list[dict]:
        """Convert relative block coords to absolute world coords."""
        ox, oy, oz = origin
        return [
            {
                "x": b["x"] + ox,
                "y": b["y"] + oy,
                "z": b["z"] + oz,
                "block": b["block"],
            }
            for b in blueprint.get("blocks", [])
        ]

    def _stratified_sample(self, blocks: list[dict], max_n: int) -> list[dict]:
        """Sample blocks evenly across y-layers (stratified by height)."""
        if len(blocks) <= max_n:
            return list(blocks)

        # Group by y, sample proportionally
        by_y: dict[int, list[dict]] = {}
        for b in blocks:
            by_y.setdefault(b["y"], []).append(b)

        per_layer = max(1, max_n // len(by_y))
        sampled: list[dict] = []
        for layer_blocks in by_y.values():
            sampled.extend(random.sample(layer_blocks, min(per_layer, len(layer_blocks))))

        # If still over limit, final trim
        if len(sampled) > max_n:
            sampled = random.sample(sampled, max_n)

        return sampled

    # ── Bridge block query ─────────────────────────────────────────────────────

    def _query_bridge_batch(self, sampled: list[dict]) -> list[dict]:
        """Query block states via bridge POST /blocks. Returns results list."""
        positions = [{"x": b["x"], "y": b["y"], "z": b["z"]} for b in sampled]

        # Bridge allows max 200 per call; split if needed
        results: list[dict] = []
        batch_size = 200
        for i in range(0, len(positions), batch_size):
            batch = positions[i : i + batch_size]
            try:
                r = requests.post(
                    f"{self.bridge_url}/blocks",
                    json={"positions": batch},
                    timeout=30,
                )
                r.raise_for_status()
                data = r.json()
                results.extend(data.get("blocks", []))
            except Exception as exc:  # noqa: BLE001
                # Bridge unavailable — fill with "unknown"
                results.extend(
                    {"x": p["x"], "y": p["y"], "z": p["z"], "block": "unknown", "found": False}
                    for p in batch
                )
        return results

    # ── RCON spot-check ────────────────────────────────────────────────────────

    def _connect_rcon(self) -> RconClient:
        return RconClient(self._rcon_host, self._rcon_port, self._rcon_password)

    def _rcon_spot_check(
        self,
        sampled: list[dict],
        actual: list[dict],
        null_indices: list[int],
        rcon: RconClient,
    ) -> None:
        """Fill in null bridge results using RCON /data get block."""
        check_indices = null_indices[:RCON_SPOT_CHECK_LIMIT]
        for idx in check_indices:
            b = sampled[idx]
            try:
                resp = rcon.command(f"data get block {b['x']} {b['y']} {b['z']}")
                block_id = self._parse_data_get_response(resp)
                if block_id:
                    actual[idx] = {
                        "x": b["x"], "y": b["y"], "z": b["z"],
                        "block": block_id, "found": True,
                    }
                time.sleep(0.05)
            except Exception:  # noqa: BLE001
                pass  # keep as unknown

    _DATA_GET_RE = re.compile(
        r"minecraft:(\w+)",
        re.IGNORECASE,
    )

    def _parse_data_get_response(self, response: str) -> str | None:
        """Extract block ID from /data get block response string."""
        # Response looks like: "The block at ... has the following block data: {id: "minecraft:oak_planks", ...}"
        # or just "minecraft:oak_planks"
        m = self._DATA_GET_RE.search(response)
        if m:
            return f"minecraft:{m.group(1).lower()}"
        return None

    # ── LLM diagnosis ─────────────────────────────────────────────────────────

    def _llm_diagnose(
        self, blueprint: dict, errors: list[dict], completion_rate: float
    ) -> dict:
        """Use Claude to diagnose errors and generate fix commands."""
        # Summarize errors (cap at 30 for context window)
        error_summary = errors[:30]
        payload = {
            "blueprint_meta": blueprint.get("meta", {}),
            "materials": blueprint.get("materials", []),
            "completion_rate": round(completion_rate, 4),
            "error_sample": error_summary,
            "total_errors": len(errors),
        }

        messages = [
            {
                "role": "user",
                "content": (
                    f"Inspect this Minecraft build and provide your diagnosis:\n"
                    f"{json.dumps(payload, indent=2)}"
                ),
            }
        ]

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=INSPECTOR_SYSTEM_PROMPT,
                messages=messages,
            )
            raw = response.content[0].text

            # Strip markdown fences if present
            fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
            candidate = fence.group(1).strip() if fence else raw.strip()
            return json.loads(candidate)

        except Exception:  # noqa: BLE001
            # If LLM call fails, return empty diagnosis — inspection still produces a rate
            return {
                "diagnosis": "LLM diagnosis unavailable",
                "fix_commands": [],
                "should_continue": completion_rate < 0.85,
            }

    # ── Output ────────────────────────────────────────────────────────────────

    def _write_report(self, session: SessionState, report: dict) -> None:
        (session.workspace_dir / "diff_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        (session.workspace_dir / "inspector_done.json").write_text(
            json.dumps({
                "status": "DONE",
                "completion_rate": report["completion_rate"],
                "should_continue": report["should_continue"],
            }),
            encoding="utf-8",
        )
