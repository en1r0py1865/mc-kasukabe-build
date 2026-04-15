**Execute Inspector Step (inline)**:

**Source image**: <SOURCE_IMAGE_PATH> (empty if not an image input)

**Step 1: Run Block Verification**

```bash
python3 -m kasukabe.verifier --workspace workspace/<SESSION_ID> --origin <ORIGIN>
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

**Step 3: Blueprint Fidelity Check (flat image builds only)**

If `<SOURCE_IMAGE_PATH>` is non-empty AND blueprint `size.z <= 10` AND `min(size.x, size.y) >= 20`:

```bash
python3 -m kasukabe.fidelity --workspace workspace/<SESSION_ID> --source-image <SOURCE_IMAGE_PATH>
```

Read `fidelity_result.json` (note `pixel_diff_ratio`, `unknown_pixel_ratio`, `aspect_ratio_match`, `unknown_blocks`), `fidelity_comparison.png`, and each `fidelity_crop_N.png`.
Blocks in `unknown_blocks` render as magenta — this is a palette gap, not a build error. `unknown_pixel_ratio` shows what fraction of render pixels are affected.
If `aspect_ratio_match < 0.8`, the blueprint has significantly different proportions than the source. Treat this as a fidelity issue and lower `blueprint_fidelity`, regardless of how `pixel_diff_ratio` looks.
If `unknown_pixel_ratio > 0.3`, `pixel_diff_ratio` is unreliable due to low palette coverage. Rely on direct visual comparison of the source image vs `fidelity_render.png`. Do not lower `blueprint_fidelity` solely because of palette gaps — judge based on visible (non-magenta) portions.

Judge `blueprint_fidelity` (0.0-1.0): 0.9+ faithful, 0.7-0.89 minor, <0.7 needs revision.
If `blueprint_fidelity < 0.7`: list `semantic_issues` and set `needs_architect_revision = true`.

If conditions are not met, set `fidelity_check_performed = false`.

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
  "errors": [...],
  "blueprint_fidelity": 0.82,
  "pixel_diff_ratio": 0.15,
  "semantic_issues": [],
  "fidelity_check_performed": true
}
```

Write `workspace/<SESSION_ID>/inspector_done.json`:
```json
{"status": "DONE", "completion_rate": 0.85, "should_continue": true, "fidelity_check_performed": true, "blueprint_fidelity": 0.82, "needs_architect_revision": false}
```
When fidelity check was not performed: set `fidelity_check_performed = false` and omit `blueprint_fidelity` and `needs_architect_revision`.

After completing:
- If `needs_architect_revision == true`: handle architect revision (see Step 4d).
- If `completion_rate >= 0.85` and (`blueprint_fidelity >= 0.7` or fidelity was not checked): break loop, proceed to summary.
- If `should_continue == false`: break loop.
- Otherwise: continue to next iteration.
