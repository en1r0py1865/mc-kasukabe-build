**Execute Builder Step (inline)**:

Run the Python builder module to execute Minecraft commands:

```bash
python -m kasukabe.agents.builder --workspace workspace/<SESSION_ID> --origin <ORIGIN> --size <SIZE>
```

After execution, read `workspace/<SESSION_ID>/build_log.json` and `workspace/<SESSION_ID>/builder_done.json`.

**Error Handling**:
- If the builder exits non-zero, read stderr for the error message.
- Common issues: bridge not running, RCON connection refused, commands.txt missing.
- Report the error clearly — do NOT retry. The Foreman will decide what to do.

Check `builder_done.json` — if BLOCKED, stop.
