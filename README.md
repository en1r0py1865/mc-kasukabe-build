# kasukabe — Minecraft AI Building Studio

AI-powered Minecraft building automation. Give it an image or video of a structure,
and kasukabe will analyze, plan, build, and self-correct — all inside Claude Code.

**No API key management needed.** Runs on [Claude Code](https://claude.ai/claude-code) — authentication is handled by your Claude Code session.

## The Pipeline

    /kasukabe-build house.jpg at 100,64,200 size 12x8x10

```
Input (image/video)
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
| `/kasukabe-build` | **Foreman** | The full pipeline. Parses your input, creates a workspace, spawns each agent as a subagent in sequence. Iterates Planner → Builder → Inspector up to 3 times until the build hits 85% completion. One command, entire build. |
| `/kasukabe-extract-frames` | **Video Processor** | Standalone keyframe extraction. Scene-change detection with time-based fallback, outputs up to 8 JPEG frames at 1280×720. Use independently or let `/kasukabe-build` call it automatically for video input. |

### Internal agents (spawned automatically by `/kasukabe-build`)

| Agent | Role | Input → Output |
|-------|------|---------------|
| **Architect** | Vision Analyst | Images → `blueprint.json` (block-level build plan with materials, layers, coordinates) |
| **Planner** | Command Strategist | `blueprint.json` → `commands.txt` (WorldEdit bulk fills + vanilla setblock, absolute coords) |
| **Builder** | Executor | `commands.txt` → blocks in world (RCON for vanilla, Mineflayer bridge for WorldEdit) |
| **Inspector** | QA Engineer | World state vs blueprint → `diff_report.json` (completion rate, diagnosis, fix commands) |

## Requirements

- [Claude Code](https://claude.ai/claude-code) CLI (authenticated)
- Python 3.11+
- Node.js 18+ (for Mineflayer bridge in `bridge/`)
- Minecraft Paper server with [FAWE](https://github.com/IntellectualSites/FastAsyncWorldEdit) plugin
- ffmpeg (for video input): `brew install ffmpeg`

## Installation

```bash
# Install Python dependencies
pip install -e .

# Install Claude Code skills
bash setup.sh
```

`setup.sh` renders skill templates and symlinks `/kasukabe-build` and `/kasukabe-extract-frames` into `~/.claude/skills/`.

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
/kasukabe-build timelapse.mp4 at 100,64,200
/kasukabe-build cabin.png
/kasukabe-extract-frames walkthrough.mp4
```

## Server Setup

### 1. Start Paper server with FAWE

```bash
cd ~/minecraft-paper && ./start.sh
```

### 2. Start Mineflayer bridge

```bash
cd bridge && npm install && node server.js
```

The bridge connects a Mineflayer bot to the Minecraft server and exposes an HTTP API on port 3001. It handles WorldEdit command execution and block state queries for the Inspector.

### 3. Op the bridge bot

```
op ClawBot
```

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
PYTHONPATH=. python3 scripts/gen_skills.py
```

## License

MIT
