#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_TARGET="$HOME/.claude/skills"

echo "=== kasukabe skill setup ==="

# Step 1: Generate SKILL.md from templates
echo "Rendering skill templates..."
PYTHONPATH="$SCRIPT_DIR" python3 "$SCRIPT_DIR/scripts/gen_skills.py"

# Step 2: Create skills directory if needed
mkdir -p "$SKILLS_TARGET"

# Step 3: Symlink user-facing skills
for skill in kasukabe-build kasukabe-extract-frames; do
    src="$SCRIPT_DIR/kasukabe/skills/$skill"
    dst="$SKILLS_TARGET/$skill"
    if [ -L "$dst" ]; then
        rm "$dst"
    fi
    ln -sfn "$src" "$dst"
    echo "  linked: $dst -> $src"
done

echo ""
echo "Installed skills:"
echo "  /kasukabe-build          — Build structures from images/video"
echo "  /kasukabe-extract-frames — Extract keyframes from video"
echo ""
echo "Done. Restart Claude Code to pick up new skills."
