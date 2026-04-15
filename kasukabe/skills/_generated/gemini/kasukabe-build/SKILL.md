---
name: kasukabe-build
description: >
  Build Minecraft structures from images, video, or building guide directories. Orchestrates the full pipeline:
  video extraction -> visual analysis -> command planning -> building -> inspection.
---

# Kasukabe Build

Build a Minecraft structure from an image, video, or directory of guide images.

## Usage

```
/kasukabe-build <path-to-image-or-video-or-directory> at <x>,<y>,<z> size <W>x<H>x<L>
```

Examples:
- `/kasukabe-build house.jpg at 100,64,200 size 12x8x10`
- `/kasukabe-build house.jpg at 100,64,200 size 12x8x10 --player Steve`
- `/kasukabe-build timelapse.mp4 at 100,64,200`
- `/kasukabe-build cabin.png` (origin defaults to 100,64,200, size auto-detected)
- `/kasukabe-build ./buildit-castle/ at 100,64,200 size 20x30x20` (directory auto-enables guide mode)
- `/kasukabe-build ./buildit-castle/ at 100,64,200 --mode guide --style "nether theme"`
- `/kasukabe-build house.jpg at 100,64,200 --mode guide --style "dark oak variant"`



## Pipeline

You are the Foreman. Follow these steps exactly.

### Step 0: Parse Input

Extract from the user's message:
- `input_path`: path to image (jpg/png/gif/webp), video (mp4/mov/avi/mkv/webm), or directory
- `origin`: x,y,z coordinates (default: 100,64,200)
- `size`: WxHxL blocks (default: 0x0x0 = auto-detect)
- `player_name`: optional player name (from `--player` flag, default: none)
- `style_directive`: from `--style "..."` flag (default: empty). Influences material/aesthetic choices.

Determine `source_type`:
- If `input_path` is a directory (check with `test -d`): `source_type = "directory"`
- If `input_path` ends with .mp4/.mov/.avi/.mkv/.webm: `source_type = "video"`
- Otherwise: `source_type = "image"`

Determine `input_mode`:
- If `--mode guide` is specified OR `source_type = "directory"`: `input_mode = "guide"`
- Otherwise: `input_mode = "standard"`

Determine `source_image_path`:
- If `source_type = "image"`: `source_image_path = <absolute path to input_path>`
- Otherwise: `source_image_path = ""` (empty)

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
SESSION_ID=$(python3 -c "import uuid; print(uuid.uuid4().hex[:12])")
mkdir -p workspace/$SESSION_ID/frames
```

Write `workspace/$SESSION_ID/input_meta.json`:
```json
{
  "session_id": "<SESSION_ID>",
  "source_path": "<absolute path to input>",
  "source_type": "image|video|directory",
  "input_mode": "standard|guide",
  "style_directive": "",
  "origin": [x, y, z],
  "size": [W, H, L]
}
```

### Step 2: Video Processing (if input is video)

If the input file ends with .mp4/.mov/.avi/.mkv/.webm, run video frame extraction:
```bash
python3 -m kasukabe.video_processor --input <input_path> --output-dir workspace/<SESSION_ID>/frames
```
Report how many frames were extracted.

### Step 2.5: Directory Processing (if source_type = "directory")

If the input is a directory, find and copy all image files into the workspace in one step:

```bash
find <input_path> -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.gif' -o -iname '*.webp' \) -print0 | sort -z | xargs -0 -I {} cp {} workspace/<SESSION_ID>/frames/
```

Count the copied files:
```bash
IMAGE_COUNT=$(ls workspace/<SESSION_ID>/frames/ | wc -l | tr -d ' ')
```

If `IMAGE_COUNT` is 0, **stop immediately** and tell the user:
> No image files found in directory `<input_path>`. Supported formats: jpg, jpeg, png, gif, webp.

If `IMAGE_COUNT` > 20, report a warning (but continue automatically):
> Note: Found N images — this is a large set and may increase processing time and cost.

Report: `Found N guide images in <input_path>.`

The image files for the Architect are now in `workspace/<SESSION_ID>/frames/`.

### Step 3: Architect (once)

Activate the Architect skill:

```
activate_skill("kasukabe-architect")
```

Provide this context to the activated skill:

> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>
> **Size**: <SIZE> (0x0x0 = auto-detect)
> **Image files**: <IMAGE_FILES>
> **Input mode**: <INPUT_MODE>
> **Style directive**: <STYLE_DIRECTIVE>
>
> Read each image file, analyze the structure, and write blueprint.json and architect_done.json to the workspace.
> If input mode is "guide", follow the Guide Mode instructions in the skill.

After the skill completes, read `workspace/<SESSION_ID>/architect_done.json`. If status is BLOCKED, stop and report the reason.


### Step 4: Iteration Loop (max 3)

Track: `architect_revised = false`

For iteration = 1, 2, 3:

#### 4a: Planner

Activate the Planner skill:

```
activate_skill("kasukabe-planner")
```

If iteration > 1, first read `workspace/<SESSION_ID>/diff_report.json` and extract `fix_commands`.

Provide this context to the activated skill:

> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>
> **Size**: <SIZE>
> [If iteration > 1]: **Fix commands from previous inspection**: [fix_commands list]
>
> Read blueprint.json, plan the construction, write commands.txt and planner_done.json.

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

Activate the Builder skill:

```
activate_skill("kasukabe-builder")
```

Provide this context to the activated skill:

> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>
> **Size**: <SIZE>

Check `builder_done.json` — if BLOCKED, stop.


#### 4c: Inspector

Pass `source_image_path` to the Inspector (used for fidelity check on flat image builds).

Activate the Inspector skill:

```
activate_skill("kasukabe-inspector")
```

Provide this context to the activated skill:

> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>
> **Source image**: <SOURCE_IMAGE_PATH> (empty if not an image input)

The skill runs world verification (Step 1-2), then fidelity check (Step 3) if source image is provided and blueprint is flat (`size.z <= 10 AND min(size.x, size.y) >= 20`).

After the skill completes, read `workspace/<SESSION_ID>/inspector_done.json`:
- If `needs_architect_revision == true`: handle architect revision (see Step 4d).
- If `completion_rate >= 0.85` and (`blueprint_fidelity >= 0.7` or fidelity was not checked): break loop, proceed to summary.
- If `should_continue == false`: break loop.
- Otherwise: continue to next iteration.


#### 4d: Decision

Read `workspace/<SESSION_ID>/inspector_done.json` and apply the first matching rule:

1. **Architect revision needed (first time)**:
   IF `needs_architect_revision == true` AND `architect_revised == false`:
   → Run architect revision:

   Activate the Architect skill in **Revision Mode**:

```
activate_skill("kasukabe-architect")
```

Provide this context to the activated skill:

> **Mode**: Revision
> **Workspace**: workspace/<SESSION_ID>
> **Original source images**: <IMAGE_FILES>
> **Previous blueprint**: workspace/<SESSION_ID>/blueprint.json
> **Fidelity comparison**: workspace/<SESSION_ID>/fidelity_comparison.png
> **Fidelity crops**: workspace/<SESSION_ID>/fidelity_crop_0.png, fidelity_crop_1.png, ... (all that exist)
> **Fidelity result**: workspace/<SESSION_ID>/fidelity_result.json
> **Diff report**: workspace/<SESSION_ID>/diff_report.json (see `semantic_issues` and `blueprint_fidelity`)
>
> Follow the **Revision Mode** instructions:
> 1. Read original source images (ground truth)
> 2. Read comparison and crop images to understand differences
> 3. Read previous blueprint.json and semantic_issues from diff_report.json
> 4. Fix flagged regions — preserve correct areas
> 5. Overwrite blueprint.json and write architect_done.json

After the skill completes, read `workspace/<SESSION_ID>/architect_done.json`. If status is BLOCKED, stop and report the reason.


   → Set `architect_revised = true`
   → Continue to next iteration (re-plan + re-build from revised blueprint)

2. **Build complete**:
   ELIF `completion_rate >= 0.85` AND (`blueprint_fidelity >= 0.7` OR `fidelity_check_performed == false`):
   → Break, proceed to Step 5

3. **No further fixes possible**:
   ELIF `should_continue == false`:
   → Break, proceed to Step 5

4. **Architect revision already attempted**:
   ELIF `needs_architect_revision == true` AND `architect_revised == true`:
   → Break, proceed to Step 5 (fidelity issues persist after 1 revision attempt)

5. **Normal fix path**:
   ELSE:
   → Continue to next iteration (apply `fix_commands` from `diff_report.json`)

### Step 5: Summary

Write `workspace/<SESSION_ID>/foreman_summary.json`:
```json
{
  "session_id": "<SESSION_ID>",
  "phase": "DONE",
  "iterations": N,
  "completion_rate": 0.XX,
  "blueprint_fidelity": 0.XX,
  "architect_revised": false,
  "workspace": "workspace/<SESSION_ID>/"
}
```
Omit `blueprint_fidelity` if fidelity check was not performed.

Report the final status to the user.

### Reporting Rule For Image Murals

When the build is based on a photo or mural:

- Do not claim the result is faithful to the original image based only on `completion_rate`.
- If verification passed but the reference image was not re-checked after a semantic patch, report that the world matches the current blueprint, not necessarily the source image.
- If the user reports a semantic mismatch in a small feature, treat that as a real build error and continue from the original reference image, not from the assumption that verifier success means the feature is correct.

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

