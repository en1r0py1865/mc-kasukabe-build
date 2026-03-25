"""Architect agent — analyzes visual input and generates a Minecraft blueprint."""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

import anthropic

from kasukabe.models import PipelineBlocked, SessionState

# ── Blueprint JSON schema (validated at runtime) ─────────────────────────────

BLUEPRINT_SCHEMA_DOC = """
{
  "meta": {
    "name": "descriptive building name",
    "size": {"x": int, "y": int, "z": int},
    "style": "architectural style string",
    "confidence": float  // 0.0–1.0
  },
  "materials": [
    {"block": "minecraft:block_id", "count": int, "usage": "walls|roof|floor|etc"}
  ],
  "layers": [
    {
      "y_offset": int,           // 0-based from ground
      "description": "what this layer is",
      "primary_block": "minecraft:block_id"
    }
  ],
  "blocks": [
    {"x": int, "y": int, "z": int, "block": "minecraft:block_id"}
  ]
}
"""

ARCHITECT_SYSTEM_PROMPT = f"""You are a Minecraft building architect. Analyze the provided image(s) \
of a real-world or Minecraft structure and produce a precise JSON blueprint for constructing it \
in Minecraft 1.21.

Respond ONLY with valid JSON matching this schema — no explanation, no markdown code fences:
{BLUEPRINT_SCHEMA_DOC}

Rules:
- All block IDs must be valid Minecraft 1.21 Java Edition IDs (minecraft: namespace, lowercase)
- Use common blocks: oak_planks, stone, cobblestone, oak_log, glass, oak_stairs, oak_slab, \
  stone_bricks, bricks, dirt, sand, gravel, oak_fence, oak_door, torch, lantern, etc.
- Coordinates in blocks[] are RELATIVE to origin (0-indexed, origin = 0,0,0)
- y=0 is ground level; y increases upward
- size.x = width (X axis), size.y = height, size.z = depth (Z axis)
- For buildings larger than 20×20×20: include representative blocks for each structural element \
  (walls, corners, roof edges) rather than every single block — be comprehensive but not exhaustive
- layers[] must cover every y_offset from 0 to size.y-1
- confidence: 0.9 if materials are clearly visible, 0.5 if guessing from context, 0.3 if very uncertain
- If size hint is provided (non-zero), scale the structure to fit within that size
"""

CORRECTION_PROMPT = """Your previous response was not valid JSON or did not match the required schema.
Please respond ONLY with valid JSON matching the blueprint schema. No markdown, no explanation.
The JSON must have: meta (name, size, style, confidence), materials (array), layers (array), blocks (array).
All block IDs must start with "minecraft:"."""

MAX_IMAGE_SIZE = 8  # maximum images per Claude API call


class Architect:
    """Analyzes visual input (images or video frames) to generate a Minecraft blueprint."""

    def __init__(self, api_key: str | None = None, model: str = "claude-opus-4-5"):
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model

    # ── Public interface ───────────────────────────────────────────────────────

    def analyze(self, session: SessionState) -> dict:
        """Load images for this session, call Claude, write and return blueprint.

        Args:
            session: Current session state (provides workspace_dir and origin).

        Returns:
            Blueprint dict (also written to workspace_dir/blueprint.json).

        Raises:
            PipelineBlocked: If no images found or Claude returns non-JSON after retry.
        """
        image_contents = self._load_images(session)
        if not image_contents:
            raise PipelineBlocked("No images found in workspace. Provide an image or video.")

        size_hint = session.size
        size_text = (
            f"Target size: {size_hint[0]}×{size_hint[1]}×{size_hint[2]} blocks."
            if any(s > 0 for s in size_hint)
            else "Auto-detect size from the image."
        )

        user_message = (
            f"Analyze this structure and generate a Minecraft blueprint. "
            f"Build origin will be at world coordinates {session.origin}. "
            f"{size_text} "
            f"Provide ONLY the JSON blueprint."
        )

        blueprint = self._call_claude(image_contents, user_message)
        blueprint = self._inject_origin(blueprint, session.origin)
        self._write_blueprint(session, blueprint)
        return blueprint

    # ── Private helpers ────────────────────────────────────────────────────────

    def _load_images(self, session: SessionState) -> list[dict]:
        """Return Claude API image content blocks for this session.

        Priority: frames/ directory (video input) → source image from input_meta.json.
        """
        workspace = session.workspace_dir
        image_blocks: list[dict] = []

        # Check frames directory (video input)
        frames_dir = workspace / "frames"
        if frames_dir.is_dir():
            frames = sorted(frames_dir.glob("frame_*.jpg"))[:MAX_IMAGE_SIZE]
            for frame in frames:
                image_blocks.append(self._encode_image(frame))

        # Fall back to source image
        if not image_blocks:
            meta_path = workspace / "input_meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                source = Path(meta.get("source_path", ""))
                if source.exists():
                    image_blocks.append(self._encode_image(source))
            # Also check if input_path itself is an image
            if not image_blocks and Path(session.input_path).exists():
                image_blocks.append(self._encode_image(Path(session.input_path)))

        return image_blocks

    def _call_claude(self, image_contents: list[dict], user_text: str) -> dict:
        """Call Claude API with images, parse JSON response. Retry once on failure."""
        messages: list[dict] = [
            {
                "role": "user",
                "content": [*image_contents, {"type": "text", "text": user_text}],
            }
        ]

        for attempt in range(2):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=ARCHITECT_SYSTEM_PROMPT,
                messages=messages,
            )
            raw = response.content[0].text

            blueprint = self._parse_json(raw)
            if blueprint is not None and self._is_valid_blueprint(blueprint):
                return blueprint

            # Retry with correction prompt
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": CORRECTION_PROMPT})

        raise PipelineBlocked(
            "Architect: Claude returned invalid blueprint JSON after 2 attempts. "
            f"Last response preview: {raw[:200]}"
        )

    def _parse_json(self, text: str) -> dict | None:
        """Extract and parse JSON from Claude's response, handling markdown fences."""
        # Strip markdown code fences if present
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
        candidate = fence_match.group(1).strip() if fence_match else text.strip()

        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None

    def _is_valid_blueprint(self, bp: dict) -> bool:
        """Check blueprint has required top-level keys and valid block IDs."""
        required = {"meta", "materials", "layers", "blocks"}
        if not required.issubset(bp.keys()):
            return False
        # Verify block IDs in materials
        for m in bp.get("materials", []):
            if not str(m.get("block", "")).startswith("minecraft:"):
                return False
        return True

    def _inject_origin(self, blueprint: dict, origin: tuple[int, int, int]) -> dict:
        """Add absolute origin to blueprint meta (used by Planner for coordinate math)."""
        blueprint.setdefault("meta", {})
        blueprint["meta"]["origin"] = {"x": origin[0], "y": origin[1], "z": origin[2]}
        return blueprint

    def _write_blueprint(self, session: SessionState, blueprint: dict) -> None:
        """Write blueprint.json and architect_done.json to workspace."""
        session.workspace_dir.mkdir(parents=True, exist_ok=True)
        (session.workspace_dir / "blueprint.json").write_text(
            json.dumps(blueprint, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        block_count = len(blueprint.get("blocks", []))
        (session.workspace_dir / "architect_done.json").write_text(
            json.dumps({"status": "DONE", "block_count": block_count}), encoding="utf-8"
        )

    def _encode_image(self, path: Path) -> dict:
        """Base64-encode an image file for the Claude API."""
        suffix = path.suffix.lower()
        media_type_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
        media_type = media_type_map.get(suffix, "image/jpeg")
        data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        }
