# kasukabe — Minecraft AI Building Studio

AI-powered Minecraft building from images and video. Give kasukabe a reference image or video of a structure, and it will analyze, plan, build, and self-correct inside your Minecraft world.

## Available Commands

| Command | Description |
|---------|-------------|
| `/kasukabe-build` | Full build pipeline. Analyzes input, generates a blueprint, places blocks, inspects, and iterates up to 3x until completion rate >= 85%. |
| `/kasukabe-extract-frames` | Standalone keyframe extraction from video. Scene-change detection with time-based fallback, outputs up to 8 JPEG frames at 1280x720. |

### Usage Examples

```
/kasukabe-build house.jpg at 100,64,200 size 12x8x10
/kasukabe-build house.jpg at 100,64,200 size 12x8x10 --player Steve
/kasukabe-build timelapse.mp4 at 100,64,200
/kasukabe-build cabin.png
/kasukabe-extract-frames walkthrough.mp4
```

## Pipeline

```
Input (image/video)
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

## Platform: Gemini CLI

### Installation

```bash
bash setup.sh --host gemini
```

This renders skill templates for use with the Gemini CLI.

### How It Works

- Skills are loaded via `activate_skill`
- The Foreman activates each pipeline skill, provides context (workspace, origin, size), and each skill completes its task by writing output files

### Usage

In Gemini CLI:

```
/kasukabe-build house.jpg at 100,64,200 size 12x8x10
```

