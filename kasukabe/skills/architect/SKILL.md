---
name: kasukabe-architect
description: >
  Visual analysis agent for Minecraft building design. Analyzes images or video frames
  of a structure and produces a structured JSON blueprint (blueprint.json) describing
  how to reconstruct it in Minecraft. Trigger when given visual input of a building
  and asked to generate a Minecraft blueprint.
metadata:
  kasukabe:
    role: architect
    inputs: [workspace/{session_id}/frames/*.jpg, workspace/{session_id}/input_meta.json]
    outputs: [workspace/{session_id}/blueprint.json, workspace/{session_id}/architect_done.json]
---

# Architect Role

Analyzes visual input (images or video frames) to produce a structured Minecraft
building blueprint. This is the first and only step run once per build session.

## Workflow

### STEP 1 — Input Validation
- Check `workspace/{session_id}/frames/` for extracted video frames
- If frames/ is empty or absent, read `workspace/{session_id}/input_meta.json` → `source_path`
- BLOCKED if no image input can be found

### STEP 2 — Vision Analysis
Call Claude API (claude-opus-4-5 or better) with all available frames (max 8) as base64 images.
Analyze:
- Overall structure type (house, tower, wall, bridge, castle, etc.)
- Approximate dimensions (W × H × L in blocks)
- Primary materials per structural element (walls, roof, floor, windows, doors)
- Layer-by-layer composition from ground up
- Notable features (overhangs, arches, decorative details)

### STEP 3 — Blueprint Generation
Write `workspace/{session_id}/blueprint.json` with schema:
```json
{
  "meta": {
    "name": "<descriptive name>",
    "size": {"x": W, "y": H, "z": L},
    "origin": {"x": ox, "y": oy, "z": oz},
    "style": "<architectural style>",
    "confidence": 0.0-1.0
  },
  "materials": [
    {"block": "minecraft:<id>", "count": <estimated>, "usage": "<walls|roof|floor|etc>"}
  ],
  "layers": [
    {"y_offset": 0, "description": "<layer description>", "primary_block": "minecraft:<id>"}
  ],
  "blocks": [
    {"x": <rel>, "y": <rel>, "z": <rel>, "block": "minecraft:<id>"}
  ]
}
```

### STEP 4 — Validation
- All block IDs must be `minecraft:*` format
- Block count must be plausible for stated size
- Write `architect_done.json`: `{"status": "DONE", "block_count": N}`

## Completion Status

**DONE**: blueprint.json written, all block IDs valid, architect_done.json has status DONE

**BLOCKED**:
- No images found in workspace
- Claude returns invalid JSON after 2 retries
- Building detected as too large (> 50×50×50) — architect should note this

**NEEDS_CONTEXT**:
- Origin coordinates missing and cannot be inferred
- Building style is ambiguous in a way that significantly affects material selection
