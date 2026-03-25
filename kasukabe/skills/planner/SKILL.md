---
name: kasukabe-planner
description: >
  Command planning agent. Reads blueprint.json and generates commands.txt containing
  WorldEdit and vanilla Minecraft commands to construct the building. Requires
  blueprint.json to exist (run Architect first). On iterations > 1, accepts
  fix_commands from Inspector to prepend as corrections.
metadata:
  kasukabe:
    role: planner
    inputs: [workspace/{session_id}/blueprint.json]
    outputs: [workspace/{session_id}/commands.txt, workspace/{session_id}/planner_done.json]
---

# Planner Role

Converts a Minecraft blueprint into an ordered, executable command sequence.

## Workflow

### STEP 1 — Read Blueprint
Load `workspace/{session_id}/blueprint.json`.
Extract: origin (ox, oy, oz), size (W, H, L), layers[], blocks[].
BLOCKED if blueprint.json missing or malformed.

### STEP 2 — Strategy Selection
For each layer in blueprint.layers:
- Full footprint, solid fill → WorldEdit `//pos1`, `//pos2`, `//set`
- Rectangular sub-region → vanilla `/fill`
- Single block → vanilla `/setblock`

Priority: WorldEdit //set (bulk) > vanilla /fill (rect) > vanilla /setblock (single)

### STEP 3 — Command Generation
Generate commands in this order:
1. Clear zone: `fill ox oy oz (ox+W-1) (oy+H-1) (oz+L-1) minecraft:air`
2. For each layer bottom-up: appropriate fill/set commands with ABSOLUTE coordinates
3. Individual blocks from blueprint.blocks[]

Output format (commands.txt):
```
# VANILLA
fill 100 64 200 109 64 209 minecraft:stone
setblock 104 67 204 minecraft:glass_pane
# WORLDEDIT
//pos1 100 65 200
//pos2 109 69 209
//set minecraft:oak_log
```

### STEP 4 — Write Output
Call write_commands tool with the full command list.
Write planner_done.json: `{"status": "DONE", "command_count": N}`

## Completion Status

**DONE**: commands.txt written, planner_done.json has status DONE

**BLOCKED**:
- blueprint.json missing
- write_commands not called after max turns
- Blueprint has zero blocks

**NEEDS_CONTEXT**:
- Blueprint confidence < 0.4 and materials are ambiguous
