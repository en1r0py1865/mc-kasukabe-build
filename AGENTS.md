# kasukabe — Minecraft AI Building Studio

AI-powered Minecraft building from images, video, or building guide directories. Give kasukabe a reference image, video, or a directory of guide screenshots, and it will analyze, plan, build, and self-correct inside your Minecraft world.

## Available Commands

| Command | Description |
|---------|-------------|
| `/kasukabe-build` | Full build pipeline. Accepts images, video, or guide directories. Generates a blueprint, places blocks, inspects, and iterates up to 3x until completion rate >= 85%. |
| `/kasukabe-extract-frames` | Standalone keyframe extraction from video. Scene-change detection with time-based fallback, outputs up to 8 JPEG frames at 1280x720. |

### Usage Examples

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

## Pipeline

```
Input (image/video/directory)
    |
[Architect]   -- vision analysis --> blueprint.json
    |
[Planner]     -- command strategy --> commands.txt
    |
[Builder]     -- RCON + bridge --> blocks placed in world
    |
[Inspector]   -- block verification + LLM diagnosis --> diff_report.json
    |
[Foreman]     -- iterates up to 3x until completion_rate >= 85%
```

## Requirements

- Python 3.11+
- Node.js 18+ (for Mineflayer bridge in `bridge/`)
- Minecraft Paper server with [FAWE](https://github.com/IntellectualSites/FastAsyncWorldEdit) plugin
- ffmpeg (for video input): `brew install ffmpeg`

## Environment Setup

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

