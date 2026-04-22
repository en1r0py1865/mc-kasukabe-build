## Platform: Codex CLI

### Installation

```bash
bash setup.sh --host codex
```

This renders skill templates and places them in `.agents/skills/`.

### How It Works

- Skills are installed in `.agents/skills/` within the project
- `/kasukabe-build`, `/kasukabe-pixel`, and `/kasukabe-extract-frames` are available as inline skills
- All pipeline steps execute inline within the Foreman's execution context (no subagent dispatch)
- Each step runs sequentially: Architect -> Planner -> Builder -> Inspector (or the deterministic pixel pipeline for `/kasukabe-pixel`)

### Usage

In Codex CLI:

```
/kasukabe-build house.jpg at 100,64,200 size 12x8x10
/kasukabe-pixel portrait.png at 100,64,200 --size 64x64
/kasukabe-pixel portrait.png at 100,64,200 --size 64x64 --region 8,8,56,56
```
