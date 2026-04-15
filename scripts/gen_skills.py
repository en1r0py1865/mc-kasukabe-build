#!/usr/bin/env python3
"""Render SKILL.md.tmpl templates into per-platform SKILL.md files.

Supports multi-platform generation for claude, codex, and gemini.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PROJECT_ROOT / "kasukabe" / "skills"

HOSTS = ("claude", "codex", "gemini")

# Mapping from host name to root entry filename
ENTRY_FILENAMES: dict[str, str] = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "gemini": "GEMINI.md",
}

# All placeholders that use spawn partials
SPAWN_PLACEHOLDERS = (
    "spawn_architect",
    "spawn_architect_revision",
    "spawn_planner",
    "spawn_builder",
    "spawn_inspector",
)


def _load_partial(partials_dir: Path, name: str) -> str:
    """Load a partial file, raising FileNotFoundError if missing."""
    path = partials_dir / name
    if not path.exists():
        raise FileNotFoundError(f"Missing partial: {path}")
    return path.read_text(encoding="utf-8")


def _build_replacements(partials_dir: Path, host: str) -> dict[str, str]:
    """Build the placeholder -> content mapping for a given host."""
    replacements: dict[str, str] = {}

    # Shared
    replacements["{{minecraft_context}}"] = _load_partial(
        partials_dir, "minecraft_context.md"
    )

    # Platform-specific
    replacements["{{platform_instructions}}"] = _load_partial(
        partials_dir, f"platform_{host}.md"
    )

    # Model configuration (only meaningful for Claude)
    model_config_path = partials_dir / f"model_config_{host}.md"
    replacements["{{model_configuration}}"] = (
        model_config_path.read_text(encoding="utf-8") if model_config_path.exists() else ""
    )

    # Spawn partials
    for name in SPAWN_PLACEHOLDERS:
        replacements[f"{{{{{name}}}}}"] = _load_partial(
            partials_dir / f"spawn_{host}", f"{name}.md"
        )

    return replacements


def _apply_replacements(content: str, replacements: dict[str, str]) -> str:
    """Apply all placeholder replacements to content."""
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    return content


def render_skills_for_host(
    skills_dir: Path,
    host: str,
    *,
    check: bool = False,
) -> list[Path]:
    """Render all SKILL.md.tmpl files for a single host.

    Templates are read from skill subdirectories under skills_dir.
    Output is written to skills_dir/_generated/{host}/{skill}/SKILL.md.

    If check=True, no files are written; returns list of paths that are
    out of date (empty list means everything is in sync).
    """
    partials_dir = skills_dir / "_partials"
    replacements = _build_replacements(partials_dir, host)

    generated_dir = skills_dir / "_generated" / host
    results: list[Path] = []

    for tmpl_path in sorted(skills_dir.rglob("SKILL.md.tmpl")):
        # Skip _partials and _generated directories
        if "_partials" in tmpl_path.parts or "_generated" in tmpl_path.parts:
            continue

        content = tmpl_path.read_text(encoding="utf-8")
        rendered = _apply_replacements(content, replacements)

        # Determine skill name from parent directory
        skill_name = tmpl_path.parent.name
        out_path = generated_dir / skill_name / "SKILL.md"

        if check:
            if not out_path.exists() or out_path.read_text(encoding="utf-8") != rendered:
                results.append(out_path)
                print(f"  STALE: {out_path.relative_to(skills_dir)}")
        else:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(rendered, encoding="utf-8")
            results.append(out_path)
            print(f"  rendered: {out_path.relative_to(skills_dir)}")

    return results


def render_entry_file(
    project_root: Path,
    host: str,
    *,
    check: bool = False,
) -> Path | None:
    """Render PLATFORM.md.tmpl into the host-specific root entry file.

    Returns the output path if generated/stale, or None if skipped.
    """
    tmpl_path = project_root / "PLATFORM.md.tmpl"
    if not tmpl_path.exists():
        print(f"  skipped: PLATFORM.md.tmpl not found")
        return None

    partials_dir = project_root / "kasukabe" / "skills" / "_partials"
    platform_specific = _load_partial(partials_dir, f"entry_{host}.md")

    content = tmpl_path.read_text(encoding="utf-8")
    rendered = content.replace("{{platform_specific}}", platform_specific)

    out_filename = ENTRY_FILENAMES[host]
    out_path = project_root / out_filename

    if check:
        if not out_path.exists() or out_path.read_text(encoding="utf-8") != rendered:
            print(f"  STALE: {out_filename}")
            return out_path
        return None
    else:
        out_path.write_text(rendered, encoding="utf-8")
        print(f"  rendered: {out_filename}")
        return out_path


def render_skills(skills_dir: Path | None = None) -> list[Path]:
    """Backward-compatible entry point.

    Generates skills for claude host by default.
    Used by existing tests.
    """
    skills_dir = skills_dir or SKILLS_DIR
    return render_skills_for_host(skills_dir, "claude")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate platform-specific SKILL.md files from templates."
    )
    parser.add_argument(
        "--host",
        choices=[*HOSTS, "all"],
        default="all",
        help="Target platform (default: all)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check freshness without writing; exit 1 if out of date",
    )
    args = parser.parse_args()

    hosts = list(HOSTS) if args.host == "all" else [args.host]
    stale: list[Path] = []

    for host in hosts:
        action = "Checking" if args.check else "Generating"
        print(f"{action} skill files for {host}...")
        results = render_skills_for_host(
            SKILLS_DIR, host, check=args.check
        )
        if args.check:
            stale.extend(results)
        else:
            print(f"  -> {len(results)} skill files")

    # Entry files
    for host in hosts:
        action = "Checking" if args.check else "Generating"
        print(f"{action} entry file for {host}...")
        result = render_entry_file(PROJECT_ROOT, host, check=args.check)
        if args.check and result is not None:
            stale.append(result)

    if args.check:
        if stale:
            print(f"\n{len(stale)} file(s) out of date. Run: python scripts/gen_skills.py")
            sys.exit(1)
        else:
            print("\nAll generated files are up to date.")
            sys.exit(0)
    else:
        total_skills = len(hosts) * 6  # approximate
        print(f"\nDone. Generated files for {len(hosts)} platform(s).")


if __name__ == "__main__":
    main()
