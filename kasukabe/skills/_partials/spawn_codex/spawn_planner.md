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
