Activate the Planner skill:

```
activate_skill("kasukabe-planner")
```

If iteration > 1, first read `workspace/<SESSION_ID>/diff_report.json` and extract `fix_commands`.

Provide this context to the activated skill:

> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>
> **Size**: <SIZE>
> [If iteration > 1]: **Fix commands from previous inspection**: [fix_commands list]
>
> Read blueprint.json, plan the construction, write commands.txt and planner_done.json.

Check `planner_done.json` — if BLOCKED, stop.
