Read the Architect skill file (installed alongside this skill):
```
architect/SKILL.md
```

Spawn an **Architect subagent** (model: opus) using the Agent tool with this prompt:

> You are the Architect subagent for Kasukabe Build.
>
> [Paste the full contents of architect/SKILL.md here]
>
> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>
> **Size**: <SIZE> (0x0x0 = auto-detect)
> **Image files**: <IMAGE_FILES>
>
> Read each image file, analyze the structure, and write blueprint.json and architect_done.json to the workspace.

After the subagent returns, Read `workspace/<SESSION_ID>/architect_done.json`. If status is BLOCKED, stop and report the reason.
