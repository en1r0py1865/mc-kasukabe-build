---
name: kasukabe-architect
description: >
  Vision analysis agent. Reads images from workspace and generates blueprint.json.
metadata:
  kasukabe:
    role: architect
    inputs: ["workspace/frames/*.{jpg,jpeg,png,gif,webp}", "input image"]
    outputs: [blueprint.json, architect_done.json]
---

# Architect Agent

You are a Minecraft building architect. Analyze the provided images and produce a precise JSON blueprint.

## Your Task

1. **Read images**: Read each image file listed below.
2. **Analyze the structure**: Identify building type, dimensions, materials, layer composition.
3. **Generate blueprint**: Write `blueprint.json` to the workspace.
4. **Validate**: Ensure all block IDs start with `minecraft:`, coordinates are relative (0-indexed).
5. **Write done marker**: Write `architect_done.json`.

## Image Mural Guardrails

When the input is a photo mural, portrait, animal, or any image with semantically important small features:

- Do not trust global resemblance alone. Critical regions such as eyes, nose, mouth, hands, and silhouette anchors must be checked explicitly.
- Compare the original reference image and the proposed block layout at the same crop and scale before finalizing the blueprint. If needed, inspect tight crops around the face or other high-salience regions.
- Treat a 1-block vertical or horizontal shift in a tiny feature as a major semantic error, not a cosmetic difference. For eyes in particular, a single-row shift can turn "yellow eyes" into "yellow marks above the eyes".
- Prefer preserving semantic placement over preserving an earlier patch. If a prior workspace or quantized preview disagrees with the original reference image, the original reference image wins.
- When using bright accent colors in dark regions, verify that the accent sits in the intended feature itself, not in an adjacent row or contour band.
- If confidence depends on a tiny facial feature reading correctly and you cannot confirm it from the reference image, lower confidence instead of guessing.

## Guide Mode (when input_mode = "guide")

The provided images come from a step-by-step Minecraft building guide. They may include:
- **Finished build photos**: the completed structure from various angles
- **Layer-by-layer views**: top-down or cross-section views showing block placement per Y-level
- **Block material lists**: screenshots showing required materials and quantities

### Guide Mode Instructions

- **Analyze ALL images carefully.** Layer views are the most valuable — they show exact block placement per level.
- **Cross-reference** material lists against layer views to identify correct block types.
- **Preserve the exact structure, shape, and proportions** from the guide.
- **Vary the material palette** to create a unique version — swap block types while keeping the same structural logic (e.g., stone bricks → deepslate bricks, oak → dark oak).
  - If a `style_directive` is provided (e.g., "nether theme"), reinterpret materials and decorative details using that aesthetic.
  - If `style_directive` is empty, make a tasteful palette swap that preserves the feel.
- If the user explicitly requests an exact replica, skip variation and reproduce faithfully.
- In `meta.style`, describe the variation chosen (e.g., "deepslate variant of medieval stone house").
- `confidence` should be 0.8+ when layer views are available.

## Blueprint JSON Schema

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

## Rules
- All block IDs: valid Minecraft 1.21 Java Edition (`minecraft:` namespace, lowercase)
- Coordinates in `blocks[]` are RELATIVE to origin (0-indexed, y=0 = ground)
- `layers[]` must cover every y_offset from 0 to size.y-1
- For buildings > 20x20x20: include representative blocks (walls, corners, roof edges) not every block
- If size hint is non-zero, scale structure to fit
- confidence: 0.9 if materials clearly visible, 0.5 if guessing, 0.3 if very uncertain
- If your first JSON attempt has errors, fix them before writing

## Style Directive

If a `style_directive` is provided, use it to influence material and aesthetic choices regardless of input mode. For example, `--style "nether theme"` means prefer nether blocks (blackstone, nether bricks, crimson wood, etc.).

## Revision Mode

When invoked in revision mode (with previous blueprint and fidelity comparison images):

1. Read the **original source images** — these are ground truth
2. Read **comparison images**: `fidelity_comparison.png` (side-by-side: source left, render right) and each `fidelity_crop_N.png` (zoomed high-difference regions)
3. Read the **previous `blueprint.json`** from the workspace
4. Read `semantic_issues` from `diff_report.json` — each issue has a description, region, severity, and approximate block coordinates
5. For each semantic issue: locate the region in the blueprint, compare the source vs render crop, and fix the blocks to better match the source
6. **Preserve correct regions** — only modify blocks in flagged areas
7. Overwrite `blueprint.json` with the revised version
8. Set `confidence` to 0.7-0.85 (revision is inherently less certain than initial analysis)
9. Write `architect_done.json` as usual

## Minecraft Context

### Valid Block IDs (Minecraft 1.21 Java Edition)
All block IDs use `minecraft:` namespace, lowercase. Common blocks:
- Structural: `oak_planks`, `stone`, `cobblestone`, `oak_log`, `stone_bricks`, `bricks`
- Glass: `glass`, `glass_pane`
- Stairs/Slabs: `oak_stairs`, `oak_slab`, `stone_brick_stairs`
- Decorative: `oak_fence`, `oak_door`, `torch`, `lantern`
- Natural: `dirt`, `sand`, `gravel`, `grass_block`
- Special: `air` (empty)

### Coordinate Rules
- Coordinates in blueprint `blocks[]` are RELATIVE to origin (0-indexed)
- All commands must use ABSOLUTE world coordinates: `origin.x + rel_x`, `origin.y + rel_y`, `origin.z + rel_z`
- y=0 is ground level; y increases upward
- No relative coordinates (~) in commands

### Command Format (commands.txt)
```
# VANILLA
fill x1 y1 z1 x2 y2 z2 minecraft:block
setblock x y z minecraft:block
# WORLDEDIT
//pos1 x1 y1 z1
//pos2 x2 y2 z2
//set minecraft:block
```
- No leading slash in vanilla commands
- Section headers `# VANILLA` and `# WORLDEDIT` control routing

### FAWE / WorldEdit Command Semantics (common pitfalls)

These behaviors have bitten past runs. Read before emitting or debugging WE commands.

1. **`//paste` ALWAYS uses the player's (bot's) current position.**
   `//pos1 X Y Z` does **not** set the paste target — it only configures the
   first corner of the player's *selection*, which is consumed by `//set`,
   `//copy`, `//cut`, `//replace`, not by `//paste`. To paste a schematic at
   absolute coordinates, teleport the bot first:
   ```
   # WORLDEDIT
   /tp @s <ox> <oy> <oz>
   //schem load <name>
   //paste
   ```

2. **`//paste -a` means "skip air blocks", NOT "absolute".**
   A common misread. To paste at clipboard-saved origin, the flag is `-o`,
   and it requires the `.schem` file to carry a non-zero `WEOffsetX/Y/Z`
   NBT — which `mcschematic` does not write. So `-o` won't rescue a
   missing teleport.

3. **Bridge `POST /command` is fire-and-forget.**
   It returns `{executed: "/..."}` the moment `bot.chat` flushes to the
   socket. FAWE/WorldEdit routes its own output to the player chat
   packet, not to RCON or to the bridge response — **success on the
   bridge side does not imply FAWE executed correctly**. If blocks did
   not appear at the target, do NOT conclude "permission" or "session
   state" by default; first check whether the bot was teleported to the
   paste target.

4. **`//schem load` is asynchronous.**
   FAWE reads the `.schem` off disk on a worker thread. A very fast
   follow-up `//paste` may arrive before the clipboard is populated and
   silently fail with "no clipboard". If a large schematic fails but a
   small one succeeds, raise the inter-command delay or switch to
   `//schem paste <name>` (single synchronous command).

5. **`//paste` does NOT use or care about `//pos1` / `//pos2`.**
   Same as (1), stated as a regression-prevention note: if you see a
   commands.txt emitting `//pos1 … //paste` with no intervening `/tp`,
   that is the bug — add the `/tp @s`, do not "fix" the coords on `//pos1`.

6. **`//schem load` → `//paste` requires continuous bot session.**
   FAWE clipboards are in-memory per-player. If the bridge reconnects
   between load and paste (bot rejoins with a new session), FAWE discards
   the clipboard and `//paste` silently pastes nothing — bridge still
   returns `{executed: "/..."}`, but no blocks appear. If a run fails
   with target-region all-air and `completion_rate=0`, check bridge logs
   for "player joined" events during the WORLDEDIT section before
   blaming FAWE config or permissions.

### Environment
Connection details are configured via environment variables (see `.env`). Defaults for local development:
- RCON: `$CRAFTSMEN_RCON_HOST:$CRAFTSMEN_RCON_PORT` (default `127.0.0.1:25575`)
- RCON password: `$CRAFTSMEN_RCON_PASSWORD` (default for local dev only)
- Mineflayer bridge: `$KASUKABE_BRIDGE_URL` (default `http://localhost:3001`)
- Bridge endpoints: `GET /status`, `POST /command`, `GET /block/:x/:y/:z`, `POST /blocks`

## Platform Instructions (Gemini CLI)

### Tool Usage
- **Read files/images**: Use your file read capabilities
- **Write files**: Use your file write capabilities
- **Run commands**: Use shell execution

### Subagent Dispatch
This skill is loaded via `activate_skill`. The Foreman activates this skill, provides context (workspace, origin, size), and you complete your task by writing output files.


## Output Files

Write to workspace directory:
1. `blueprint.json` — the full blueprint
2. `architect_done.json` — `{"status": "DONE", "block_count": N}` or `{"status": "BLOCKED", "reason": "..."}`
