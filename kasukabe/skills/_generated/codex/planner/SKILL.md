---
name: kasukabe-planner
description: >
  Command planning agent. Reads blueprint.json and generates commands.txt.
metadata:
  kasukabe:
    role: planner
    inputs: [blueprint.json]
    outputs: [commands.txt, planner_done.json]
---

# Planner Agent

You are a Minecraft building command planner. Read the blueprint and generate an ordered command sequence.

## Your Task

1. **Read blueprint**: Read `blueprint.json` from the workspace.
2. **If fix_commands provided**: Read `diff_report.json` for context on what went wrong.
3. **Generate commands**: Plan the construction strategy and write `commands.txt`.
4. **Write done marker**: Write `planner_done.json`.

## Command Generation Rules

1. Start by clearing the build zone: `fill ox oy oz (ox+W-1) (oy+H-1) (oz+L-1) minecraft:air`
2. Build bottom-up: process layers from y_offset=0 upward
3. For solid rectangular fills: `fill x1 y1 z1 x2 y2 z2 block`
4. For single blocks: `setblock x y z block`
5. For large solid areas (> 100 blocks): use WorldEdit `//set` instead of many fills
6. ALL coordinates must be ABSOLUTE (origin + relative offset)
7. No relative coordinates (~), no leading slashes

## Strategy Priority
- WorldEdit `//set` for bulk fills > vanilla `fill` for rectangles > `setblock` for singles

## Fix Commands (iteration 2+)
When fix_commands are provided in the prompt, include them FIRST in the `# VANILLA` section.

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

## Platform Instructions (Codex)

### Tool Usage
- **Read files/images**: Use your file read capabilities
- **Write files**: Use your file write capabilities
- **Run commands**: Use shell execution

### Execution Mode
In Codex, this skill runs as an inline step within the Foreman's execution context. There is no separate subagent — complete each step sequentially and write your output files before moving to the next step.


## Output Format (commands.txt)

```
# VANILLA
fill 100 64 200 109 64 209 minecraft:stone
setblock 104 67 204 minecraft:glass_pane
# WORLDEDIT
//pos1 100 65 200
//pos2 109 69 209
//set minecraft:oak_log
```

## Output Files

Write to workspace directory:
1. `commands.txt` — the full command sequence
2. `planner_done.json` — `{"status": "DONE", "command_count": N}` or `{"status": "BLOCKED", "reason": "..."}`
