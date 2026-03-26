## Platform: Claude Code

### Installation

```bash
bash setup.sh --host claude
```

This renders skill templates and symlinks `/kasukabe-build` and `/kasukabe-extract-frames` into `~/.claude/skills/`.

### How It Works

- Skills are installed as symlinks in `~/.claude/skills/`
- The Foreman (`/kasukabe-build`) dispatches subagents using the **Agent** tool
- Model selection per subagent:
  - **Architect**: opus (vision analysis benefits from the strongest model)
  - **Planner**: sonnet
  - **Inspector**: sonnet
- Builder runs inline (RCON/bridge commands via Bash)

### Usage

In Claude Code:

```
/kasukabe-build house.jpg at 100,64,200 size 12x8x10
```
