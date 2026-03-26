Read `inspector/SKILL.md` (installed alongside this skill).

Spawn an **Inspector subagent** (model: sonnet) using the Agent tool with this prompt:

> You are the Inspector subagent for Kasukabe Build.
>
> [Paste the full contents of inspector/SKILL.md here]
>
> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>

After return, Read `workspace/<SESSION_ID>/diff_report.json`:
- If `completion_rate >= 0.85`: break loop, proceed to summary.
- If `should_continue == false`: break loop.
- Otherwise: continue to next iteration.
