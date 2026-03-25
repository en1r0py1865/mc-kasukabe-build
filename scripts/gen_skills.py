#!/usr/bin/env python3
"""Render SKILL.md.tmpl templates into SKILL.md files."""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "kasukabe" / "skills"


def render_skills(skills_dir: Path | None = None) -> list[Path]:
    """Render all .tmpl files, replacing {{minecraft_context}}.

    Returns list of generated SKILL.md paths.
    """
    skills_dir = skills_dir or SKILLS_DIR
    partials_dir = skills_dir / "_partials"

    # Load partials
    mc_context_path = partials_dir / "minecraft_context.md"
    if not mc_context_path.exists():
        raise FileNotFoundError(f"Missing partial: {mc_context_path}")
    mc_context = mc_context_path.read_text(encoding="utf-8")

    generated: list[Path] = []

    for tmpl_path in sorted(skills_dir.rglob("SKILL.md.tmpl")):
        # Skip _partials
        if "_partials" in tmpl_path.parts:
            continue

        content = tmpl_path.read_text(encoding="utf-8")
        rendered = content.replace("{{minecraft_context}}", mc_context)

        out_path = tmpl_path.with_name("SKILL.md")
        out_path.write_text(rendered, encoding="utf-8")
        generated.append(out_path)
        print(f"  rendered: {out_path.relative_to(skills_dir)}")

    return generated


def main() -> None:
    print("Generating SKILL.md files...")
    generated = render_skills()
    print(f"Done. Generated {len(generated)} skill files.")


if __name__ == "__main__":
    main()
