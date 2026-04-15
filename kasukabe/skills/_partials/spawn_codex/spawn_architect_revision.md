**Execute Architect Revision Step (inline)**:

You are now acting as the Architect in **Revision Mode**. The previous blueprint had fidelity issues — fix the flagged regions.

**Workspace**: workspace/<SESSION_ID>
**Original source images**: <IMAGE_FILES>
**Previous blueprint**: workspace/<SESSION_ID>/blueprint.json
**Fidelity comparison**: workspace/<SESSION_ID>/fidelity_comparison.png
**Fidelity crops**: workspace/<SESSION_ID>/fidelity_crop_0.png, fidelity_crop_1.png, ... (all that exist)
**Fidelity result**: workspace/<SESSION_ID>/fidelity_result.json
**Diff report**: workspace/<SESSION_ID>/diff_report.json (see `semantic_issues` and `blueprint_fidelity`)

1. **Read original source images** — these are ground truth
2. **Read comparison images**: `fidelity_comparison.png` (source left, render right) and each `fidelity_crop_N.png`
3. **Read previous `blueprint.json`** and `semantic_issues` from `diff_report.json`
4. For each semantic issue: locate the region in the blueprint, compare source vs render, fix blocks
5. **Preserve correct regions** — only modify blocks in flagged areas
6. Overwrite `workspace/<SESSION_ID>/blueprint.json` with the revised version
7. Set `confidence` to 0.7-0.85
8. Write `workspace/<SESSION_ID>/architect_done.json`:
   - Success: `{"status": "DONE", "block_count": N}`
   - Failure: `{"status": "BLOCKED", "reason": "..."}`

After completing, read `workspace/<SESSION_ID>/architect_done.json`. If status is BLOCKED, stop and report the reason.
