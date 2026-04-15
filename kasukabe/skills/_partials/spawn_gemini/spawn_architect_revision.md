Activate the Architect skill in **Revision Mode**:

```
activate_skill("kasukabe-architect")
```

Provide this context to the activated skill:

> **Mode**: Revision
> **Workspace**: workspace/<SESSION_ID>
> **Original source images**: <IMAGE_FILES>
> **Previous blueprint**: workspace/<SESSION_ID>/blueprint.json
> **Fidelity comparison**: workspace/<SESSION_ID>/fidelity_comparison.png
> **Fidelity crops**: workspace/<SESSION_ID>/fidelity_crop_0.png, fidelity_crop_1.png, ... (all that exist)
> **Fidelity result**: workspace/<SESSION_ID>/fidelity_result.json
> **Diff report**: workspace/<SESSION_ID>/diff_report.json (see `semantic_issues` and `blueprint_fidelity`)
>
> Follow the **Revision Mode** instructions:
> 1. Read original source images (ground truth)
> 2. Read comparison and crop images to understand differences
> 3. Read previous blueprint.json and semantic_issues from diff_report.json
> 4. Fix flagged regions — preserve correct areas
> 5. Overwrite blueprint.json and write architect_done.json

After the skill completes, read `workspace/<SESSION_ID>/architect_done.json`. If status is BLOCKED, stop and report the reason.
