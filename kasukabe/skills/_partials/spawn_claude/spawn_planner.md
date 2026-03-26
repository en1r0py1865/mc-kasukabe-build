Read `planner/SKILL.md` (installed alongside this skill).

If iteration > 1, also Read `workspace/<SESSION_ID>/diff_report.json` and extract `fix_commands`.

Spawn a **Planner subagent** (model: sonnet) using the Agent tool with this prompt:

> You are the Planner subagent for Kasukabe Build.
>
> [Paste the full contents of planner/SKILL.md here]
>
> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>
> **Size**: <SIZE>
> [If iteration > 1]: **Fix commands from previous inspection**: [fix_commands list]
>
> Read blueprint.json, plan the construction, write commands.txt and planner_done.json.

Check `planner_done.json` — if BLOCKED, stop.
