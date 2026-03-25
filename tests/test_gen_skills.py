# tests/test_gen_skills.py
"""Tests for the skill template renderer."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


class TestGenSkills:
    def test_placeholder_expanded(self, tmp_path):
        """{{minecraft_context}} is replaced with actual content."""
        from scripts.gen_skills import render_skills

        # Create minimal structure
        partials = tmp_path / "kasukabe" / "skills" / "_partials"
        partials.mkdir(parents=True)
        (partials / "minecraft_context.md").write_text("BLOCK_IDS_HERE")

        skill_dir = tmp_path / "kasukabe" / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md.tmpl").write_text("# Test\n{{minecraft_context}}\nEnd")

        render_skills(tmp_path / "kasukabe" / "skills")

        output = (skill_dir / "SKILL.md").read_text()
        assert "BLOCK_IDS_HERE" in output
        assert "{{minecraft_context}}" not in output

    def test_no_raw_placeholders_remain(self, tmp_path):
        """No {{ }} placeholders in rendered output."""
        from scripts.gen_skills import render_skills

        partials = tmp_path / "kasukabe" / "skills" / "_partials"
        partials.mkdir(parents=True)
        (partials / "minecraft_context.md").write_text("context")

        skill_dir = tmp_path / "kasukabe" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md.tmpl").write_text("{{minecraft_context}}")

        render_skills(tmp_path / "kasukabe" / "skills")

        output = (skill_dir / "SKILL.md").read_text()
        assert "{{" not in output

    def test_skips_partials_directory(self, tmp_path):
        """_partials directory is not treated as a skill."""
        from scripts.gen_skills import render_skills

        partials = tmp_path / "kasukabe" / "skills" / "_partials"
        partials.mkdir(parents=True)
        (partials / "minecraft_context.md").write_text("context")

        render_skills(tmp_path / "kasukabe" / "skills")

        assert not (partials / "SKILL.md").exists()
