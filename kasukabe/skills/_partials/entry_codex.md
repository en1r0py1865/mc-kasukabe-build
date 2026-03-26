## Platform: Codex CLI

### Installation

```bash
bash setup.sh --host codex
```

This renders skill templates and places them in `.agents/skills/`.

### How It Works

- Skills are installed in `.agents/skills/` within the project
- All pipeline steps execute inline within the Foreman's execution context (no subagent dispatch)
- Each step runs sequentially: Architect -> Planner -> Builder -> Inspector

### Usage

In Codex CLI:

```
/kasukabe-build house.jpg at 100,64,200 size 12x8x10
```
