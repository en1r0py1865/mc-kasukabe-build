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
