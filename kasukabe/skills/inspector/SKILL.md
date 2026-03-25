---
name: kasukabe-inspector
description: >
  Build verification agent. Compares blueprint expected blocks against actual world state
  using Mineflayer bridge batch queries + RCON spot-checks. Uses Claude to diagnose errors
  and generate targeted fix commands. Outputs diff_report.json with completion_rate and
  fix_commands for the next iteration.
metadata:
  kasukabe:
    role: inspector
    inputs: [workspace/{session_id}/blueprint.json]
    outputs: [workspace/{session_id}/diff_report.json, workspace/{session_id}/inspector_done.json]
---

# Inspector Role

Verifies build quality by sampling blueprint blocks and checking them against the world.

## Workflow

### STEP 1 — Load Blueprint
Read `workspace/{session_id}/blueprint.json`.
Convert relative coords to absolute using origin.
BLOCKED if blueprint.json missing.

### STEP 2 — Stratified Sample
Sample up to 200 blocks from the expected block list, distributed evenly across y-layers.

### STEP 3 — Bridge Batch Query
POST /blocks to Mineflayer bridge with sampled positions.
Returns actual block types at each coordinate.

### STEP 4 — RCON Spot-Check
For positions where bridge returned `found: false` (chunk not loaded):
Use RCON `/data get block x y z` to verify (max 20 fallback queries).

### STEP 5 — Compute Completion Rate
`completion_rate = correct_blocks / sampled_blocks`

### STEP 6 — LLM Diagnosis
Send error summary to Claude API. Returns:
- `diagnosis`: what went wrong
- `fix_commands`: up to 20 targeted setblock/fill commands
- `should_continue`: whether another iteration is needed

### STEP 7 — Write Output
Write `diff_report.json` and `inspector_done.json`.

## Completion Status

**DONE**: diff_report.json written, inspector_done.json status DONE

**BLOCKED**:
- blueprint.json missing
- Blueprint has zero blocks

**should_continue: false** when completion_rate ≥ 0.85 (Foreman will stop iterating)
