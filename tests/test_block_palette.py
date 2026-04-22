"""Tests for kasukabe.block_palette."""
from __future__ import annotations

from kasukabe.block_palette import (
    BLOCK_COLORS,
    BlockConstraint,
    BlockEntry,
    FALLBACK_COLOR,
    all_entries,
    get_color,
    get_entry,
    list_palette,
)


class TestBlockColors:
    def test_all_16_concrete_colors_present(self):
        colors = [
            "white", "orange", "magenta", "light_blue", "yellow", "lime",
            "pink", "gray", "light_gray", "cyan", "purple", "blue",
            "brown", "green", "red", "black",
        ]
        for c in colors:
            key = f"minecraft:{c}_concrete"
            assert key in BLOCK_COLORS, f"missing {key}"

    def test_all_16_wool_colors_present(self):
        colors = [
            "white", "orange", "magenta", "light_blue", "yellow", "lime",
            "pink", "gray", "light_gray", "cyan", "purple", "blue",
            "brown", "green", "red", "black",
        ]
        for c in colors:
            key = f"minecraft:{c}_wool"
            assert key in BLOCK_COLORS, f"missing {key}"

    def test_values_are_rgb_tuples(self):
        for block_id, color in BLOCK_COLORS.items():
            assert isinstance(color, tuple), f"{block_id}: not a tuple"
            assert len(color) == 3, f"{block_id}: not length 3"
            assert all(0 <= c <= 255 for c in color), f"{block_id}: out of range"

    def test_fallback_is_magenta(self):
        assert FALLBACK_COLOR == (255, 0, 255)


class TestGetColor:
    def test_known_block(self):
        assert get_color("minecraft:white_concrete") == (207, 213, 214)

    def test_unknown_block_returns_fallback(self):
        assert get_color("minecraft:totally_fake_block") == FALLBACK_COLOR

    def test_strips_blockstate_properties(self):
        color = get_color("minecraft:oak_planks[waterlogged=true]")
        assert color == BLOCK_COLORS["minecraft:oak_planks"]

    def test_strips_complex_blockstate(self):
        color = get_color("minecraft:stone_bricks[facing=north,half=top]")
        assert color == BLOCK_COLORS["minecraft:stone_bricks"]

    def test_no_blockstate_unchanged(self):
        color = get_color("minecraft:stone")
        assert color == BLOCK_COLORS["minecraft:stone"]


class TestBlockEntry:
    def test_all_entries_nonempty(self):
        assert len(all_entries()) >= 300

    def test_effective_rgb_switches_on_view_face(self):
        # oak_log has distinct top (rings) vs side (bark)
        e = get_entry("minecraft:oak_log[axis=y]")
        assert e is not None
        top = e.effective_rgb("top")
        side = e.effective_rgb("side")
        # rings vs bark differ visually
        assert top != side

    def test_get_entry_unknown_returns_none(self):
        assert get_entry("minecraft:totally_not_real") is None


class TestConstraints:
    def test_list_palette_default_excludes_all_constraints(self):
        entries = list_palette(face="side")
        for e in entries:
            assert e.constraints == BlockConstraint.NONE, f"{e.block_id} leaked in"

    def test_list_palette_can_include_translucent(self):
        default = {e.block_id for e in list_palette(face="side")}
        with_tr = {e.block_id for e in list_palette(face="side", include=BlockConstraint.TRANSLUCENT)}
        # Must be a superset, and must add something (ice / glass are TRANSLUCENT)
        assert default <= with_tr
        assert len(with_tr) > len(default)

    def test_gravity_blocks_are_filtered_by_default(self):
        for e in list_palette(face="side"):
            assert "sand" not in e.block_id.lower() or "sandstone" in e.block_id.lower(), \
                f"sand-type block {e.block_id} leaked into default palette"

    def test_biome_tinted_excluded_by_default(self):
        ids = {e.block_id for e in list_palette(face="side")}
        assert "minecraft:grass_block" not in ids
        assert "minecraft:oak_leaves" not in ids


class TestBackwardCompat:
    def test_get_color_returns_side_rgb(self):
        # oak_log's side face = bark
        e = get_entry("minecraft:oak_log[axis=y]")
        # get_color strips state; match against the stateless alias.
        stripped = get_color("minecraft:oak_log")
        assert stripped == e.side_rgb
