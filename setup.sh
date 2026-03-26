#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GENERATED_DIR="$SCRIPT_DIR/kasukabe/skills/_generated"

# All skills to install (user-facing + internal)
SKILLS=(kasukabe-build kasukabe-extract-frames architect planner builder inspector)

# ── Defaults ──────────────────────────────────────────────────────────
HOST="auto"
LOCAL_INSTALL=false

# ── Parse arguments ───────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            HOST="${2:-auto}"
            shift 2
            ;;
        --local)
            LOCAL_INSTALL=true
            shift
            ;;
        -h|--help)
            cat <<'USAGE'
Usage: bash setup.sh [OPTIONS]

Options:
  --host <target>   auto | claude | codex | gemini | all  (default: auto)
  --local           Install to project-local directories instead of global
  -h, --help        Show this help

Examples:
  bash setup.sh                  # auto-detect installed CLIs
  bash setup.sh --host claude    # Claude Code only
  bash setup.sh --host all       # all platforms
  bash setup.sh --local          # project-local install
USAGE
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# ── Auto-detection ────────────────────────────────────────────────────
detect_platforms() {
    local platforms=()

    # Claude Code: ~/.claude/ exists or claude command available
    if [[ -d "$HOME/.claude" ]] || command -v claude &>/dev/null; then
        platforms+=(claude)
    fi

    # Codex: codex command available
    if command -v codex &>/dev/null; then
        platforms+=(codex)
    fi

    # Gemini: gemini command available
    if command -v gemini &>/dev/null; then
        platforms+=(gemini)
    fi

    # Fallback: if nothing detected, default to Claude Code
    if [[ ${#platforms[@]} -eq 0 ]]; then
        echo "  No CLI detected — falling back to Claude Code" >&2
        platforms+=(claude)
    fi

    echo "${platforms[@]}"
}

# ── Resolve target platforms ──────────────────────────────────────────
resolve_hosts() {
    case "$HOST" in
        auto)    detect_platforms ;;
        all)     echo "claude codex gemini" ;;
        claude|codex|gemini) echo "$HOST" ;;
        *)
            echo "Unknown host: $HOST" >&2
            exit 1
            ;;
    esac
}

# ── Symlink helper ────────────────────────────────────────────────────
link_skill() {
    local src="$1"
    local dst="$2"

    if [[ ! -d "$src" ]]; then
        echo "  WARN: source not found, skipping: $src" >&2
        return
    fi

    if [[ -L "$dst" ]]; then
        local existing
        existing="$(readlink "$dst")"
        if [[ "$existing" == "$src" ]]; then
            echo "  ok (unchanged): $dst"
            return
        fi
        echo "  WARN: overwriting existing symlink: $dst -> $existing"
        rm "$dst"
    elif [[ -e "$dst" ]]; then
        echo "  WARN: $dst exists and is not a symlink — skipping" >&2
        return
    fi

    ln -sfn "$src" "$dst"
    echo "  linked: $dst -> $src"
}

# ── Platform installers ──────────────────────────────────────────────

install_claude() {
    local target_dir

    if $LOCAL_INSTALL; then
        target_dir="$SCRIPT_DIR/.claude/skills"
        echo "Claude Code (project-local):"
    else
        target_dir="$HOME/.claude/skills"
        echo "Claude Code (global):"
    fi

    mkdir -p "$target_dir"

    for skill in "${SKILLS[@]}"; do
        link_skill "$GENERATED_DIR/claude/$skill" "$target_dir/$skill"
    done
    echo ""
}

install_codex() {
    # Codex is always project-local
    local target_dir="$SCRIPT_DIR/.agents/skills"
    echo "Codex (project-local):"

    mkdir -p "$target_dir"

    for skill in "${SKILLS[@]}"; do
        link_skill "$GENERATED_DIR/codex/$skill" "$target_dir/$skill"
    done
    echo ""
}

install_gemini() {
    local target_dir="$SCRIPT_DIR/.gemini/skills"
    echo "Gemini (project-local):"

    mkdir -p "$target_dir"

    for skill in "${SKILLS[@]}"; do
        link_skill "$GENERATED_DIR/gemini/$skill" "$target_dir/$skill"
    done
    echo ""
}

# ── Main ──────────────────────────────────────────────────────────────

echo "=== kasukabe skill setup ==="
echo ""

# Step 1: Generate skills from templates
echo "Rendering skill templates..."
PYTHONPATH="$SCRIPT_DIR" python3 "$SCRIPT_DIR/scripts/gen_skills.py"
echo ""

# Step 2: Resolve which platforms to install for
read -ra PLATFORMS <<< "$(resolve_hosts)"
echo "Platforms: ${PLATFORMS[*]}"
echo ""

# Step 3: Install for each platform
for platform in "${PLATFORMS[@]}"; do
    case "$platform" in
        claude) install_claude ;;
        codex)  install_codex  ;;
        gemini) install_gemini ;;
    esac
done

# Step 4: Summary
echo "Installed skills:"
echo "  /kasukabe-build          — Build structures from images/video"
echo "  /kasukabe-extract-frames — Extract keyframes from video"
echo "  /architect               — Vision analysis (internal)"
echo "  /planner                 — Command strategy (internal)"
echo "  /builder                 — Block placement (internal)"
echo "  /inspector               — Build verification (internal)"
echo ""
echo "Done. Restart your AI coding assistant to pick up new skills."
