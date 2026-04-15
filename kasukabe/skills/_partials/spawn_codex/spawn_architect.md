**Execute Architect Step (inline)**:

You are now acting as the Architect. Analyze the provided images and produce a precise JSON blueprint.

**Workspace**: workspace/<SESSION_ID>
**Origin**: <ORIGIN>
**Size**: <SIZE> (0x0x0 = auto-detect)
**Image files**: <IMAGE_FILES>
**Input mode**: <INPUT_MODE>
**Style directive**: <STYLE_DIRECTIVE>

1. **Read images**: Read each image file listed above.
2. **Analyze the structure**: Identify building type, dimensions, materials, layer composition. If input mode is "guide", follow the **Guide Mode** section below before proceeding. If a style directive is provided, follow the **Style Directive** section below.
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

---

#### Guide Mode (when input_mode = "guide")

The images come from a step-by-step Minecraft building guide. They may include:
- **Finished build photos**: the completed structure from various angles
- **Layer-by-layer views**: top-down or cross-section views showing block placement per Y-level
- **Block material lists**: screenshots showing required materials and quantities

Instructions:
- **Analyze ALL images carefully.** Layer views are the most valuable — they show exact block placement per level.
- **Cross-reference** material lists against layer views to identify correct block types.
- **Preserve the exact structure, shape, and proportions** from the guide.
- **Vary the material palette** to create a unique version — swap block types while keeping the same structural logic (e.g., stone bricks → deepslate bricks, oak → dark oak).
  - If a `style_directive` is provided (e.g., "nether theme"), reinterpret materials and decorative details using that aesthetic.
  - If `style_directive` is empty, make a tasteful palette swap that preserves the feel.
- If the user explicitly requests an exact replica, skip variation and reproduce faithfully.
- In `meta.style`, describe the variation chosen (e.g., "deepslate variant of medieval stone house").
- `confidence` should be 0.8+ when layer views are available.

#### Style Directive

If a `style_directive` is provided, use it to influence material and aesthetic choices **regardless of input mode**. For example, `--style "nether theme"` means prefer nether blocks (blackstone, nether bricks, crimson wood, etc.).
