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

## Model Configuration

Edit these defaults to change which models subagents use:
- **architect**: opus (vision analysis benefits from stronger model)
- **planner**: sonnet
- **inspector**: sonnet


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

Read the Architect skill file (installed alongside this skill):
```
architect/SKILL.md
```

Spawn an **Architect subagent** (model: opus) using the Agent tool with this prompt:

> You are the Architect subagent for Kasukabe Build.
>
> [Paste the full contents of architect/SKILL.md here]
>
> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>
> **Size**: <SIZE> (0x0x0 = auto-detect)
> **Image files**: <IMAGE_FILES>
>
> Read each image file, analyze the structure, and write blueprint.json and architect_done.json to the workspace.

After the subagent returns, Read `workspace/<SESSION_ID>/architect_done.json`. If status is BLOCKED, stop and report the reason.


### Step 4: Iteration Loop (max 3)

For iteration = 1, 2, 3:

#### 4a: Planner

Read `planner/SKILL.md` (installed alongside this skill).

If iteration > 1, also Read `workspace/<SESSION_ID>/diff_report.json` and extract `fix_commands`.

Spawn a **Planner subagent** (model: sonnet) using the Agent tool with this prompt:

> You are the Planner subagent for Kasukabe Build.
>
> [Paste the full contents of planner/SKILL.md here]
>
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

Read `builder/SKILL.md` (installed alongside this skill).

Spawn a **Builder subagent** using the Agent tool with this prompt:

> You are the Builder subagent for Kasukabe Build.
>
> [Paste the full contents of builder/SKILL.md here]
>
> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>
> **Size**: <SIZE>

Check `builder_done.json` — if BLOCKED, stop.


#### 4c: Inspector

Read `inspector/SKILL.md` (installed alongside this skill).

Spawn an **Inspector subagent** (model: sonnet) using the Agent tool with this prompt:

> You are the Inspector subagent for Kasukabe Build.
>
> [Paste the full contents of inspector/SKILL.md here]
>
> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>

After return, Read `workspace/<SESSION_ID>/diff_report.json`:
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

