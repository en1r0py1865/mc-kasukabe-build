---
name: kasukabe-builder
description: >
  Pure Python command executor. Reads commands.txt and executes WorldEdit commands
  via Mineflayer bridge (POST /command) and vanilla commands via RCON. Requires
  commands.txt from Planner and an active Mineflayer bot connection.
metadata:
  kasukabe:
    role: builder
    inputs: [workspace/{session_id}/commands.txt]
    outputs: [workspace/{session_id}/build_log.json, workspace/{session_id}/builder_done.json]
---

# Builder Role

Executes commands.txt sequentially to place blocks in the Minecraft world.
No LLM involved — pure Python execution.

## Execution Channels

| Section header | Channel | Method |
|---|---|---|
| `# VANILLA` | RCON | Direct socket command |
| `# WORLDEDIT` | Mineflayer bridge | POST /command (bot chat) |

## Workflow

### STEP 1 — Preflight
- Verify commands.txt exists
- Verify Mineflayer bridge is reachable (GET /status, connected=true)
- Connect RCON client

### STEP 2 — Forceload
RCON: `forceload add x1 z1 x2 z2` — ensures build zone chunks are loaded

### STEP 3 — Execute Commands
For each command in commands.txt:
- Skip blank lines and comment lines
- `# WORLDEDIT` header → switch to bridge channel
- `# VANILLA` header → switch to RCON channel
- Send command via active channel
- Record success/failure in log

Delays: RCON 0.15s/cmd, bridge 0.10s/cmd

### STEP 4 — Cleanup
RCON: `forceload remove x1 z1 x2 z2`
Write build_log.json + builder_done.json

## Completion Status

**DONE**: builder_done.json has status DONE

**BLOCKED**:
- commands.txt missing
- Mineflayer bridge not reachable
- RCON connection refused
