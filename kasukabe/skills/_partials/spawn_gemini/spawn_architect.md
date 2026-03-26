Activate the Architect skill:

```
activate_skill("kasukabe-architect")
```

Provide this context to the activated skill:

> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>
> **Size**: <SIZE> (0x0x0 = auto-detect)
> **Image files**: <IMAGE_FILES>
>
> Read each image file, analyze the structure, and write blueprint.json and architect_done.json to the workspace.

After the skill completes, read `workspace/<SESSION_ID>/architect_done.json`. If status is BLOCKED, stop and report the reason.
