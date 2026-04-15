Activate the Inspector skill:

```
activate_skill("kasukabe-inspector")
```

Provide this context to the activated skill:

> **Workspace**: workspace/<SESSION_ID>
> **Origin**: <ORIGIN>
> **Source image**: <SOURCE_IMAGE_PATH> (empty if not an image input)

The skill runs world verification (Step 1-2), then fidelity check (Step 3) if source image is provided and blueprint is flat (`size.z <= 10 AND min(size.x, size.y) >= 20`).

After the skill completes, read `workspace/<SESSION_ID>/inspector_done.json`:
- If `needs_architect_revision == true`: handle architect revision (see Step 4d).
- If `completion_rate >= 0.85` and (`blueprint_fidelity >= 0.7` or fidelity was not checked): break loop, proceed to summary.
- If `should_continue == false`: break loop.
- Otherwise: continue to next iteration.
