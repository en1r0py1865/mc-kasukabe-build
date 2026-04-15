# tests/test_gen_skills.py
"""Tests for the skill template renderer."""
from __future__ import annotations

from pathlib import Path

import pytest


def _create_partials(skills_dir: Path, mc_content: str = "context") -> Path:
    """Create a minimal _partials structure for testing."""
    partials = skills_dir / "_partials"
    partials.mkdir(parents=True, exist_ok=True)
    (partials / "minecraft_context.md").write_text(mc_content)
    (partials / "platform_claude.md").write_text("claude instructions")
    (partials / "platform_codex.md").write_text("codex instructions")
    (partials / "platform_gemini.md").write_text("gemini instructions")
    (partials / "entry_claude.md").write_text("claude entry")
    (partials / "entry_codex.md").write_text("codex entry")
    (partials / "entry_gemini.md").write_text("gemini entry")
    for host in ("claude", "codex", "gemini"):
        spawn_dir = partials / f"spawn_{host}"
        spawn_dir.mkdir(parents=True, exist_ok=True)
        for role in ("architect", "architect_revision", "planner", "builder", "inspector"):
            (spawn_dir / f"spawn_{role}.md").write_text(f"{host} {role}")
    return partials


class TestGenSkills:
    def test_placeholder_expanded(self, tmp_path):
        """{{minecraft_context}} is replaced with actual content."""
        from scripts.gen_skills import render_skills

        skills_dir = tmp_path / "kasukabe" / "skills"
        _create_partials(skills_dir, "BLOCK_IDS_HERE")

        skill_dir = skills_dir / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md.tmpl").write_text("# Test\n{{minecraft_context}}\nEnd")

        render_skills(skills_dir)

        output = (skills_dir / "_generated" / "claude" / "test-skill" / "SKILL.md").read_text()
        assert "BLOCK_IDS_HERE" in output
        assert "{{minecraft_context}}" not in output

    def test_no_raw_placeholders_remain(self, tmp_path):
        """No {{ }} placeholders in rendered output."""
        from scripts.gen_skills import render_skills

        skills_dir = tmp_path / "kasukabe" / "skills"
        _create_partials(skills_dir)

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md.tmpl").write_text("{{minecraft_context}}")

        render_skills(skills_dir)

        output = (skills_dir / "_generated" / "claude" / "my-skill" / "SKILL.md").read_text()
        assert "{{" not in output

    def test_skips_partials_directory(self, tmp_path):
        """_partials directory is not treated as a skill."""
        from scripts.gen_skills import render_skills

        skills_dir = tmp_path / "kasukabe" / "skills"
        _create_partials(skills_dir)

        render_skills(skills_dir)

        assert not (skills_dir / "_partials" / "SKILL.md").exists()

    def test_multi_host_generation(self, tmp_path):
        """render_skills_for_host generates into _generated/{host}/."""
        from scripts.gen_skills import render_skills_for_host

        skills_dir = tmp_path / "kasukabe" / "skills"
        _create_partials(skills_dir)

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md.tmpl").write_text(
            "{{minecraft_context}}\n{{platform_instructions}}"
        )

        for host in ("claude", "codex", "gemini"):
            render_skills_for_host(skills_dir, host)
            out = (skills_dir / "_generated" / host / "my-skill" / "SKILL.md").read_text()
            assert f"{host} instructions" in out
            assert "context" in out

    def test_check_mode_detects_stale(self, tmp_path):
        """--check mode returns stale files when output is missing."""
        from scripts.gen_skills import render_skills_for_host

        skills_dir = tmp_path / "kasukabe" / "skills"
        _create_partials(skills_dir)

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md.tmpl").write_text("{{minecraft_context}}")

        stale = render_skills_for_host(skills_dir, "claude", check=True)
        assert len(stale) == 1

    def test_check_mode_passes_when_fresh(self, tmp_path):
        """--check mode returns empty when files are up to date."""
        from scripts.gen_skills import render_skills_for_host

        skills_dir = tmp_path / "kasukabe" / "skills"
        _create_partials(skills_dir)

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md.tmpl").write_text("{{minecraft_context}}")

        # Generate first
        render_skills_for_host(skills_dir, "claude")
        # Check should pass
        stale = render_skills_for_host(skills_dir, "claude", check=True)
        assert len(stale) == 0

    def test_spawn_placeholders_expanded(self, tmp_path):
        """Spawn placeholders are replaced with host-specific content."""
        from scripts.gen_skills import render_skills_for_host

        skills_dir = tmp_path / "kasukabe" / "skills"
        _create_partials(skills_dir)

        skill_dir = skills_dir / "foreman"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md.tmpl").write_text(
            "{{spawn_architect}}\n{{spawn_architect_revision}}\n{{spawn_planner}}\n{{spawn_builder}}\n{{spawn_inspector}}"
        )

        render_skills_for_host(skills_dir, "codex")
        out = (skills_dir / "_generated" / "codex" / "foreman" / "SKILL.md").read_text()
        assert "codex architect" in out
        assert "codex architect_revision" in out
        assert "codex planner" in out
        assert "codex builder" in out
        assert "codex inspector" in out
