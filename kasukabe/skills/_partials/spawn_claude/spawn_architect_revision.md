Read the Architect skill file (installed alongside this skill):
```
architect/SKILL.md
```

Spawn an **Architect subagent** (model: opus) using the Agent tool with this prompt:

> You are the Architect subagent for Kasukabe Build, invoked in **Revision Mode**.
>
> [Paste the full contents of architect/SKILL.md here]
>
> **Workspace**: workspace/<SESSION_ID>
> **Original source images**: <IMAGE_FILES>
> **Previous blueprint**: workspace/<SESSION_ID>/blueprint.json
> **Fidelity comparison**: workspace/<SESSION_ID>/fidelity_comparison.png
> **Fidelity crops**: workspace/<SESSION_ID>/fidelity_crop_0.png, fidelity_crop_1.png, ... (all that exist)
> **Fidelity result**: workspace/<SESSION_ID>/fidelity_result.json
> **Diff report**: workspace/<SESSION_ID>/diff_report.json (see `semantic_issues` and `blueprint_fidelity`)
>
> Follow the **Revision Mode** instructions in the skill:
> 1. Read the original source images (ground truth)
> 2. Read the comparison and crop images to understand what differs
> 3. Read the previous blueprint.json and semantic_issues from diff_report.json
> 4. Fix flagged regions to better match the source — preserve correct areas
> 5. Overwrite blueprint.json and write architect_done.json

After the subagent returns, Read `workspace/<SESSION_ID>/architect_done.json`. If status is BLOCKED, stop and report the reason.
