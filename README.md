# kasukabe — Minecraft AI Building Studio

AI-powered Minecraft building automation. Input an image or video of a structure and kasukabe will:

1. **Analyze** the visual input (Claude vision API)
2. **Plan** the build as WorldEdit + vanilla commands
3. **Execute** commands via RCON and Mineflayer bridge
4. **Inspect** the result and self-iterate until complete (up to 3 rounds)

## Architecture

```
Input (image/video)
    ↓
[Architect]  — Claude API vision → blueprint.json
    ↓
[Planner]    — tool-use loop → commands.txt (VANILLA + WORLDEDIT sections)
    ↓
[Builder]    — Python: RCON (vanilla) + Mineflayer bridge (WorldEdit)
    ↓
[Inspector]  — bridge batch query + RCON spot-check + LLM diagnosis → diff_report.json
    ↓
[Foreman]    — iterates up to 3× until completion_rate ≥ 85%
```

## Requirements

- Python 3.11+
- Minecraft Paper server with FAWE plugin
- Mineflayer bridge running (`bridge-server.js`)
- ffmpeg (for video input)
- `ANTHROPIC_API_KEY` environment variable

## Installation

```bash
pip install -e .
```

Or with uv:

```bash
uv pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY and server settings
```

## Usage

```bash
# Build from an image
kasukabe build --input house.jpg --origin 100,64,200 --size 12x8x10

# Build from a video (size auto-detected)
kasukabe build --input timelapse.mp4 --origin 100,64,200

# Custom workspace directory
kasukabe build --input cabin.png --workspace /tmp/kasukabe-sessions
```

## Server Setup

### 1. Start Paper server with FAWE

```bash
cd /Users/elon/minecraft-paper && ./start.sh
```

### 2. Start Mineflayer bridge

```bash
node /path/to/minecraft-skill/minecraft-bridge/bridge-server.js
```

The bridge-server.js has been extended with two new endpoints:
- `GET /block/:x/:y/:z` — query block at coordinates
- `POST /blocks` — batch query up to 200 positions

### 3. Op the bridge bot

Via RCON or in-game console:
```
op ClawBot
```

## Agent Roles

See `kasukabe/skills/*/SKILL.md` for detailed workflow documentation for each agent role.

## Workspace Structure

Each build session creates a workspace directory:

```
workspace/{session_id}/
├── input_meta.json       # session metadata
├── frames/               # extracted video frames (if video input)
├── blueprint.json        # Architect output
├── commands.txt          # Planner output
├── build_log.json        # Builder execution log
├── diff_report.json      # Inspector verification report
└── foreman_summary.json  # final summary
```
