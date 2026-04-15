"""Tests for kasukabe.block_palette."""
from __future__ import annotations

from kasukabe.block_palette import BLOCK_COLORS, FALLBACK_COLOR, get_color


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
