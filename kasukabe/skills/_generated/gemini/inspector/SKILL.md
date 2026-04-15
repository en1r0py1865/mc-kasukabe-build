---
name: kasukabe-inspector
description: >
  Build verification + diagnosis subagent. Runs Python verifier, then diagnoses errors.
metadata:
  kasukabe:
    role: inspector
    inputs: [blueprint.json]
    outputs: [diff_report.json, inspector_done.json]
---

# Inspector Subagent

You verify build quality and diagnose errors. This is a two-step process.

## Step 1: Run Block Verification

Run the Python verifier module via Bash:

```bash
python -m kasukabe.verifier --workspace <WORKSPACE> --origin <ORIGIN>
```

Then Read `verification_result.json` from the workspace.

## Step 2: Diagnose Errors

Read `verification_result.json` and `blueprint.json`. Analyze the mismatches.

Based on the errors, produce a diagnosis:

1. **diagnosis**: 1-3 sentence technical description of what went wrong
2. **fix_commands**: Up to 20 targeted `setblock` or `fill` commands (absolute coords, no leading slash)
3. **should_continue**: `true` if fixes are needed, `false` if build looks complete or no meaningful fixes possible
4. **completion_rate**: Copy from verification_result.json

## Semantic Guardrails

- `completion_rate` only measures world-vs-blueprint agreement. It does **not** prove the blueprint matches the original reference image.
- If the task is an image mural or face-heavy build, treat user-reported semantic errors such as "the eye is in the wrong place" or "the yellow belongs in the eye, not above it" as blueprint-quality failures even when `completion_rate == 1.0`.
- Do not describe a build as "correct" or "matching the source" based only on verifier output. At most, say it matches the current blueprint unless the reference image was re-checked.
- When a tiny feature can flip meaning with a 1-block shift, recommend a local blueprint patch rather than relying on verifier success.

## Fix Command Rules
- Use absolute world coordinates (not relative ~)
- Include only the top 20 most critical fixes (wrong block type or missing block)
- Commands are vanilla Minecraft format: `setblock x y z minecraft:block` or `fill x1 y1 z1 x2 y2 z2 minecraft:block`

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

## Platform Instructions (Gemini CLI)

### Tool Usage
- **Read files/images**: Use your file read capabilities
- **Write files**: Use your file write capabilities
- **Run commands**: Use shell execution

### Subagent Dispatch
This skill is loaded via `activate_skill`. The Foreman activates this skill, provides context (workspace, origin, size), and you complete your task by writing output files.


## Output Files

Write to workspace directory:
1. `diff_report.json`:
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
2. `inspector_done.json`: `{"status": "DONE", "completion_rate": 0.85, "should_continue": true}`
