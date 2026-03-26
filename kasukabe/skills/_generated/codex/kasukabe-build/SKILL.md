---
name: kasukabe-build
description: >
  Build Minecraft structures from images or video. Orchestrates the full pipeline:
  video extraction -> visual analysis -> command planning -> building -> inspection.
---

# Kasukabe Build

Build a Minecraft structure from an image or video input.

## Usage

```
/kasukabe-build <path-to-image-or-video> at <x>,<y>,<z> size <W>x<H>x<L>
```

Examples:
- `/kasukabe-build house.jpg at 100,64,200 size 12x8x10`
- `/kasukabe-build house.jpg at 100,64,200 size 12x8x10 --player Steve`
- `/kasukabe-build timelapse.mp4 at 100,64,200`
- `/kasukabe-build cabin.png` (origin defaults to 100,64,200, size auto-detected)



## Pipeline

You are the Foreman. Follow these steps exactly.

### Step 0: Parse Input

Extract from the user's message:
- `input_path`: path to image (jpg/png/gif/webp) or video (mp4/mov/avi/mkv/webm)
- `origin`: x,y,z coordinates (default: 100,64,200)
- `size`: WxHxL blocks (default: 0x0x0 = auto-detect)
- `player_name`: optional player name (from `--player` flag, default: none)

### Step 0.5: Preflight Check

Before creating the workspace, verify the bridge is reachable:

```bash
curl -s --connect-timeout 3 http://localhost:3001/status
```

If the bridge is not reachable or returns an error, **stop immediately** and tell the user:

> Bridge server is not running. Start it first:
> ```
> cd bridge && npm install && node server.js
> ```
> Then re-run this command.

Do NOT proceed to Step 1 if the bridge is down.

### Step 1: Create Workspace

```bash
SESSION_ID=$(python -c "import uuid; print(uuid.uuid4().hex[:12])")
mkdir -p workspace/$SESSION_ID/frames
```

Write `workspace/$SESSION_ID/input_meta.json`:
```json
{
  "session_id": "<SESSION_ID>",
  "source_path": "<absolute path to input>",
  "source_type": "image|video",
  "origin": [x, y, z],
  "size": [W, H, L]
}
```

### Step 2: Video Processing (if input is video)

If the input file ends with .mp4/.mov/.avi/.mkv/.webm, run video frame extraction:
```bash
python -m kasukabe.video_processor --input <input_path> --output-dir workspace/<SESSION_ID>/frames
```
Report how many frames were extracted.

### Step 3: Architect (once)

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


### Step 4: Iteration Loop (max 3)

For iteration = 1, 2, 3:

#### 4a: Planner

**Execute Planner Step (inline)**:

You are now acting as the Planner. Read the blueprint and generate an ordered command sequence.

1. **Read blueprint**: Read `workspace/<SESSION_ID>/blueprint.json`.
2. **If fix_commands provided**: Read `workspace/<SESSION_ID>/diff_report.json` for context.
3. **Generate commands** following these rules:
   - Start by clearing the build zone: `fill ox oy oz (ox+W-1) (oy+H-1) (oz+L-1) minecraft:air`
   - Build bottom-up: process layers from y_offset=0 upward
   - Solid rectangular fills: `fill x1 y1 z1 x2 y2 z2 block`
   - Single blocks: `setblock x y z block`
   - Large solid areas (> 100 blocks): use WorldEdit `//set`
   - ALL coordinates must be ABSOLUTE (origin + relative offset)
   - No relative coordinates (~), no leading slashes

4. **Strategy Priority**: WorldEdit `//set` > vanilla `fill` > `setblock`

5. **Fix Commands (iteration 2+)**: Include fix_commands FIRST in the `# VANILLA` section.

6. **Write** `workspace/<SESSION_ID>/commands.txt`:
```
# VANILLA
fill 100 64 200 109 64 209 minecraft:stone
setblock 104 67 204 minecraft:glass_pane
# WORLDEDIT
//pos1 100 65 200
//pos2 109 69 209
//set minecraft:oak_log
```

7. **Write done marker**: `workspace/<SESSION_ID>/planner_done.json`:
   - Success: `{"status": "DONE", "command_count": N}`
   - Failure: `{"status": "BLOCKED", "reason": "..."}`

Check `planner_done.json` — if BLOCKED, stop.


#### 4.pre: Teleport Player (iteration 1 only)

If `player_name` is set and this is iteration 1, teleport the player to a vantage point near the build:

```bash
curl -s -X POST http://localhost:3001/command \
  -H 'Content-Type: application/json' \
  -d '{"command":"tp <player_name> <origin.x + W/2> <origin.y> <origin.z - 3>"}'
```

Print the command being executed: `Teleporting <player_name>: tp <player_name> <tp_x> <tp_y> <tp_z>`

If `player_name` is not set and this is iteration 1, print:

> Tip: Use `--player <name>` to teleport your character to the build site.

#### 4b: Builder

**Execute Builder Step (inline)**:

Run the Python builder module to execute Minecraft commands:

```bash
python -m kasukabe.agents.builder --workspace workspace/<SESSION_ID> --origin <ORIGIN> --size <SIZE>
```

After execution, read `workspace/<SESSION_ID>/build_log.json` and `workspace/<SESSION_ID>/builder_done.json`.

**Error Handling**:
- If the builder exits non-zero, read stderr for the error message.
- Common issues: bridge not running, RCON connection refused, commands.txt missing.
- Report the error clearly — do NOT retry. The Foreman will decide what to do.

Check `builder_done.json` — if BLOCKED, stop.


#### 4c: Inspector

**Execute Inspector Step (inline)**:

**Step 1: Run Block Verification**

```bash
python -m kasukabe.verifier --workspace workspace/<SESSION_ID> --origin <ORIGIN>
```

Read `workspace/<SESSION_ID>/verification_result.json`.

**Step 2: Diagnose Errors**

Read `verification_result.json` and `blueprint.json`. Analyze the mismatches and produce a diagnosis:

1. **diagnosis**: 1-3 sentence technical description of what went wrong
2. **fix_commands**: Up to 20 targeted `setblock` or `fill` commands (absolute coords, no leading slash)
3. **should_continue**: `true` if fixes are needed, `false` if build looks complete
4. **completion_rate**: Copy from verification_result.json

**Fix Command Rules**:
- Use absolute world coordinates (not relative ~)
- Include only the top 20 most critical fixes
- Format: `setblock x y z minecraft:block` or `fill x1 y1 z1 x2 y2 z2 minecraft:block`

Write `workspace/<SESSION_ID>/diff_report.json`:
```json
{
  "completion_rate": 0.85,
  "diagnosis": "...",
  "fix_commands": ["setblock ..."],
  "should_continue": true,
  "total_blueprint_blocks": N,
  "sampled_blocks": N,
  "correct_blocks": N,
  "errors": [...]
}
```

Write `workspace/<SESSION_ID>/inspector_done.json`:
`{"status": "DONE", "completion_rate": 0.85, "should_continue": true}`

After completing:
- If `completion_rate >= 0.85`: break loop, proceed to summary.
- If `should_continue == false`: break loop.
- Otherwise: continue to next iteration.


### Step 5: Summary

Write `workspace/<SESSION_ID>/foreman_summary.json`:
```json
{
  "session_id": "<SESSION_ID>",
  "phase": "DONE",
  "iterations": N,
  "completion_rate": 0.XX,
  "workspace": "workspace/<SESSION_ID>/"
}
```

Report the final status to the user.

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

### Environment
Connection details are configured via environment variables (see `.env`). Defaults for local development:
- RCON: `$CRAFTSMEN_RCON_HOST:$CRAFTSMEN_RCON_PORT` (default `127.0.0.1:25575`)
- RCON password: `$CRAFTSMEN_RCON_PASSWORD` (default for local dev only)
- Mineflayer bridge: `$KASUKABE_BRIDGE_URL` (default `http://localhost:3001`)
- Bridge endpoints: `GET /status`, `POST /command`, `GET /block/:x/:y/:z`, `POST /blocks`

