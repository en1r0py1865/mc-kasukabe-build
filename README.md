# kasukabe — Minecraft AI Building Studio

AI-powered Minecraft building automation. Give it an image, video, or directory of
building guide screenshots, and kasukabe will analyze, plan, build, and self-correct
— all inside Claude Code.

**No API key management needed.** Works with [Claude Code](https://claude.ai/claude-code), [Codex CLI](https://github.com/openai/codex), and [Gemini CLI](https://github.com/google-gemini/gemini-cli).

## The Pipeline

    /kasukabe-build house.jpg at 100,64,200 size 12x8x10

```
Input (image/video/directory)
    ↓
[Architect]   — vision analysis → blueprint.json
    ↓
[Planner]     — command strategy → commands.txt
    ↓
[Builder]     — RCON + bridge → blocks placed in world
    ↓
[Inspector]   — block verification + LLM diagnosis → diff_report.json
    ↓
[Foreman]     — iterates up to 3× until completion_rate ≥ 85%
```

## Skills

| Skill | Role | What it does |
|-------|------|-------------|
| `/kasukabe-build` | **Foreman** | The full pipeline. Accepts images, video, or guide directories. Parses your input, creates a workspace, spawns each agent as a subagent in sequence. Iterates Planner → Builder → Inspector up to 3 times until the build hits 85% completion. One command, entire build. |
| `/kasukabe-extract-frames` | **Video Processor** | Standalone keyframe extraction. Scene-change detection with time-based fallback, outputs up to 8 JPEG frames at 1280×720. Use independently or let `/kasukabe-build` call it automatically for video input. |

### Internal agents (spawned automatically by `/kasukabe-build`)

| Agent | Role | Input → Output |
|-------|------|---------------|
| **Architect** | Vision Analyst | Images → `blueprint.json` (block-level build plan with materials, layers, coordinates) |
| **Planner** | Command Strategist | `blueprint.json` → `commands.txt` (WorldEdit bulk fills + vanilla setblock, absolute coords) |
| **Builder** | Executor | `commands.txt` → blocks in world (RCON for vanilla, Mineflayer bridge for WorldEdit) |
| **Inspector** | QA Engineer | World state vs blueprint → `diff_report.json` (completion rate, diagnosis, fix commands) |

## Requirements

- AI CLI: [Claude Code](https://claude.ai/claude-code), [Codex CLI](https://github.com/openai/codex), or [Gemini CLI](https://github.com/google-gemini/gemini-cli)
- Python 3.11+
- Node.js 18+ (for Mineflayer bridge in `bridge/`)
- Minecraft Paper server with [FAWE](https://github.com/IntellectualSites/FastAsyncWorldEdit) plugin
- ffmpeg (for video input): `brew install ffmpeg`

## Installation

```bash
# Install Python dependencies
pip install -e .

# Install skills (auto-detects installed AI CLIs)
bash setup.sh

# Or install for a specific platform
bash setup.sh --host claude    # Claude Code
bash setup.sh --host codex     # Codex CLI
bash setup.sh --host gemini    # Gemini CLI
bash setup.sh --host all       # All platforms

# Project-local install (instead of global)
bash setup.sh --local
```

`setup.sh` generates platform-specific skills and installs them for your AI CLI (Claude Code, Codex, or Gemini).

## Configuration

```bash
cp .env.example .env
```

Edit `.env` with your server settings. Default values work for local development:

| Variable | Default | Description |
|----------|---------|-------------|
| `KASUKABE_BRIDGE_URL` | `http://localhost:3001` | Mineflayer bridge URL |
| `CRAFTSMEN_RCON_HOST` | `127.0.0.1` | RCON host |
| `CRAFTSMEN_RCON_PORT` | `25575` | RCON port |
| `CRAFTSMEN_RCON_PASSWORD` | `minecraft123` | RCON password (change for non-local servers) |

## Usage

In Claude Code:

```
/kasukabe-build house.jpg at 100,64,200 size 12x8x10
/kasukabe-build house.jpg at 100,64,200 size 12x8x10 --player Steve
/kasukabe-build timelapse.mp4 at 100,64,200
/kasukabe-build cabin.png
/kasukabe-build ./buildit-castle/ at 100,64,200 size 20x30x20
/kasukabe-build ./buildit-castle/ at 100,64,200 --mode guide --style "nether theme"
/kasukabe-build house.jpg at 100,64,200 --mode guide --style "dark oak variant"
/kasukabe-extract-frames walkthrough.mp4
```

Use `--player <name>` to teleport your character to the build site before construction begins.

## Server Setup

### 1. Start Paper server with FAWE

```bash
cd ~/minecraft-paper && ./start.sh
```

### 2. Start Mineflayer bridge

```bash
cd bridge && npm install && node server.js
```

> **Note:** Start the Minecraft server before launching the bridge. The bridge will retry the connection on failure, but it cannot proceed until the server is ready.

The `MC_VERSION` must match your Minecraft server version. If the bridge fails with a version mismatch error, set it explicitly:

```bash
MC_VERSION=1.21.11 node server.js
```

All available environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MC_HOST` | `localhost` | Minecraft server host |
| `MC_PORT` | `25565` | Minecraft game port |
| `MC_VERSION` | `1.21.1` | Minecraft server version (must match your server) |
| `MC_BOT_USERNAME` | `ClawBot` | Bot username |
| `MC_BRIDGE_PORT` | `3001` | Bridge HTTP API port |
| `MC_AUTH` | `offline` | Auth mode: `offline` or `microsoft` |

The bridge connects a Mineflayer bot to the Minecraft server and exposes an HTTP API on port 3001. It handles WorldEdit command execution and block state queries for the Inspector.

### 3. Grant operator privileges to the bot

Run the following command in the Minecraft server console (or in-game as an existing operator):

```
op ClawBot
```

The bot requires operator privileges to execute `fill`, `setblock`, and WorldEdit commands. If you changed `MC_BOT_USERNAME`, replace `ClawBot` with the username you configured.

## Workspace Structure

Each build session creates:

```
workspace/{session_id}/
├── input_meta.json       # session metadata
├── frames/               # extracted video frames (if video)
├── blueprint.json        # Architect output
├── commands.txt          # Planner output
├── build_log.json        # Builder execution log
├── diff_report.json      # Inspector verification report
└── foreman_summary.json  # final summary
```

## Development

```bash
# Run tests
PYTHONPATH=. pytest tests/ -v

# Regenerate skill templates after editing .tmpl files
PYTHONPATH=. python3 scripts/gen_skills.py           # all platforms
PYTHONPATH=. python3 scripts/gen_skills.py --host claude  # single platform
PYTHONPATH=. python3 scripts/gen_skills.py --check   # verify freshness (CI)
```

## License

MIT
