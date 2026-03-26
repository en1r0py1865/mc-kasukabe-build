Activate the Inspector skill:

```
activate_skill("kasukabe-inspector")
```

Provide this context to the activated skill:

> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>

After the skill completes, read `workspace/<SESSION_ID>/diff_report.json`:
- If `completion_rate >= 0.85`: break loop, proceed to summary.
- If `should_continue == false`: break loop.
- Otherwise: continue to next iteration.
