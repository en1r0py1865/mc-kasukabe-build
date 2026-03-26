**Execute Architect Step (inline)**:

You are now acting as the Architect. Analyze the provided images and produce a precise JSON blueprint.

1. **Read images**: Read each image file: <IMAGE_FILES>
2. **Analyze the structure**: Identify building type, dimensions, materials, layer composition.
3. **Generate blueprint**: Write `workspace/<SESSION_ID>/blueprint.json` with this schema:

```json
{
  "meta": {
    "name": "descriptive building name",
    "size": {"x": W, "y": H, "z": L},
    "origin": {"x": ox, "y": oy, "z": oz},
    "style": "architectural style",
    "confidence": 0.0-1.0
  },
  "materials": [
    {"block": "minecraft:block_id", "count": N, "usage": "walls|roof|floor|etc"}
  ],
  "layers": [
    {"y_offset": 0, "description": "layer description", "primary_block": "minecraft:block_id"}
  ],
  "blocks": [
    {"x": rel_x, "y": rel_y, "z": rel_z, "block": "minecraft:block_id"}
  ]
}
```

4. **Rules**:
   - All block IDs: valid Minecraft 1.21 Java Edition (`minecraft:` namespace, lowercase)
   - Coordinates in `blocks[]` are RELATIVE to origin (0-indexed, y=0 = ground)
   - `layers[]` must cover every y_offset from 0 to size.y-1
   - For buildings > 20x20x20: include representative blocks (walls, corners, roof edges)
   - If size hint is non-zero, scale structure to fit
   - confidence: 0.9 if materials clearly visible, 0.5 if guessing, 0.3 if very uncertain

5. **Write done marker**: Write `workspace/<SESSION_ID>/architect_done.json`:
   - Success: `{"status": "DONE", "block_count": N}`
   - Failure: `{"status": "BLOCKED", "reason": "..."}`

After completing, read `workspace/<SESSION_ID>/architect_done.json`. If status is BLOCKED, stop and report the reason.
