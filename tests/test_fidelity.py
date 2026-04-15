"""Tests for kasukabe.fidelity."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from kasukabe.block_palette import BLOCK_COLORS, FALLBACK_COLOR
from kasukabe.fidelity import (
    compute_pixel_diff_ratio,
    make_comparison_image,
    prepare_comparison,
    render_blueprint,
    variance_driven_crops,
)


def _make_blueprint(blocks: list[dict], size: dict) -> dict:
    """Helper to build a minimal blueprint dict."""
    return {
        "meta": {
            "name": "test",
            "size": size,
            "origin": {"x": 0, "y": 0, "z": 0},
            "style": "test",
            "confidence": 1.0,
        },
        "materials": [],
        "layers": [],
        "blocks": blocks,
    }


class TestRenderBlueprint:
    def test_single_block_correct_color(self):
        bp = _make_blueprint(
            [{"x": 0, "y": 0, "z": 0, "block": "minecraft:white_concrete"}],
            {"x": 1, "y": 1, "z": 1},
        )
        img, unknown = render_blueprint(bp)
        assert img.size == (1, 1)
        assert img.getpixel((0, 0)) == BLOCK_COLORS["minecraft:white_concrete"]
        assert unknown == []

    def test_y_flip(self):
        """y=0 should be at the bottom of the image (last row)."""
        bp = _make_blueprint(
            [
                {"x": 0, "y": 0, "z": 0, "block": "minecraft:red_concrete"},
                {"x": 0, "y": 1, "z": 0, "block": "minecraft:blue_concrete"},
            ],
            {"x": 1, "y": 2, "z": 1},
        )
        img, _ = render_blueprint(bp)
        # y=0 (red) should be at image row 1 (bottom)
        assert img.getpixel((0, 1)) == BLOCK_COLORS["minecraft:red_concrete"]
        # y=1 (blue) should be at image row 0 (top)
        assert img.getpixel((0, 0)) == BLOCK_COLORS["minecraft:blue_concrete"]

    def test_air_blocks_skipped(self):
        bp = _make_blueprint(
            [
                {"x": 0, "y": 0, "z": 0, "block": "minecraft:air"},
                {"x": 0, "y": 0, "z": 1, "block": "minecraft:stone"},
            ],
            {"x": 1, "y": 1, "z": 2},
        )
        img, _ = render_blueprint(bp)
        # Air at z=0 skipped, stone at z=1 rendered
        assert img.getpixel((0, 0)) == BLOCK_COLORS["minecraft:stone"]

    def test_min_z_wins(self):
        """Non-air block with smallest z should be rendered (front face)."""
        bp = _make_blueprint(
            [
                {"x": 0, "y": 0, "z": 5, "block": "minecraft:gold_block"},
                {"x": 0, "y": 0, "z": 2, "block": "minecraft:iron_block"},
            ],
            {"x": 1, "y": 1, "z": 6},
        )
        img, _ = render_blueprint(bp)
        assert img.getpixel((0, 0)) == BLOCK_COLORS["minecraft:iron_block"]

    def test_unknown_blocks_reported(self):
        bp = _make_blueprint(
            [{"x": 0, "y": 0, "z": 0, "block": "minecraft:unknown_thing"}],
            {"x": 1, "y": 1, "z": 1},
        )
        img, unknown = render_blueprint(bp)
        assert img.getpixel((0, 0)) == FALLBACK_COLOR
        assert "minecraft:unknown_thing" in unknown

    def test_empty_position_is_black(self):
        bp = _make_blueprint(
            [{"x": 0, "y": 0, "z": 0, "block": "minecraft:stone"}],
            {"x": 2, "y": 1, "z": 1},
        )
        img, _ = render_blueprint(bp)
        # Position (1, 0) has no block -> black
        assert img.getpixel((1, 0)) == (0, 0, 0)


class TestPrepareComparison:
    def test_resizes_to_render_dimensions(self, tmp_path):
        source = Image.new("RGB", (100, 80), (255, 0, 0))
        source_path = tmp_path / "source.png"
        source.save(source_path)

        render = Image.new("RGB", (10, 8), (0, 0, 255))
        resized, ar_match = prepare_comparison(str(source_path), render)

        assert resized.size == (10, 8)

    def test_aspect_ratio_match_identical(self, tmp_path):
        """Same aspect ratio -> ar_match == 1.0."""
        source = Image.new("RGB", (200, 100), (255, 0, 0))
        source_path = tmp_path / "source.png"
        source.save(source_path)

        render = Image.new("RGB", (20, 10), (0, 0, 255))
        _, ar_match = prepare_comparison(str(source_path), render)
        assert ar_match == pytest.approx(1.0)

    def test_aspect_ratio_match_different(self, tmp_path):
        """16:9 source + 1:1 render -> ar_match ~0.56."""
        source = Image.new("RGB", (160, 90), (255, 0, 0))  # 16:9
        source_path = tmp_path / "source.png"
        source.save(source_path)

        render = Image.new("RGB", (100, 100), (0, 0, 255))  # 1:1
        _, ar_match = prepare_comparison(str(source_path), render)
        assert ar_match == pytest.approx(0.5625, abs=0.01)


class TestMakeComparisonImage:
    def test_output_dimensions(self):
        src = Image.new("RGB", (10, 8), (255, 0, 0))
        rnd = Image.new("RGB", (10, 8), (0, 0, 255))
        comp = make_comparison_image(src, rnd)

        target = min(512, max(10, 8) * 8)  # 80
        scale = target / 10  # 8.0
        w = int(10 * scale)  # 80
        h = int(8 * scale)   # 64
        assert comp.size == (w * 2 + 4, h)

    def test_uses_nearest_scaling(self):
        """Small images should produce crisp pixel-art scaling."""
        src = Image.new("RGB", (2, 2), (255, 0, 0))
        rnd = Image.new("RGB", (2, 2), (0, 255, 0))
        comp = make_comparison_image(src, rnd)
        # Should be larger than input
        assert comp.width > 4


class TestPixelDiffRatio:
    def test_identical_images_zero(self):
        img = Image.new("RGB", (10, 10), (128, 128, 128))
        ratio, upr = compute_pixel_diff_ratio(img, img)
        assert ratio == 0.0
        assert upr == 0.0

    def test_completely_different_near_one(self):
        black = Image.new("RGB", (10, 10), (0, 0, 0))
        white = Image.new("RGB", (10, 10), (255, 255, 255))
        ratio, _ = compute_pixel_diff_ratio(black, white)
        assert ratio > 0.9

    def test_partial_diff(self):
        a = Image.new("RGB", (10, 10), (100, 100, 100))
        b = Image.new("RGB", (10, 10), (150, 150, 150))
        ratio, _ = compute_pixel_diff_ratio(a, b)
        assert 0.0 < ratio < 0.5

    def test_fallback_pixels_excluded_from_diff(self):
        """Render pixels at FALLBACK_COLOR should not contribute to diff."""
        src = Image.new("RGB", (10, 10), (255, 0, 0))
        rnd = Image.new("RGB", (10, 10), FALLBACK_COLOR)
        ratio, upr = compute_pixel_diff_ratio(src, rnd)
        assert ratio == 0.0  # all render pixels are fallback -> nothing counted
        assert upr == 1.0    # all pixels are unknown

    def test_unknown_pixel_ratio(self):
        """25% fallback pixels -> unknown_pixel_ratio == 0.25."""
        src = Image.new("RGB", (4, 4), (128, 128, 128))
        rnd = Image.new("RGB", (4, 4), (128, 128, 128))
        # Set top row (4 pixels out of 16) to fallback
        for x in range(4):
            rnd.putpixel((x, 0), FALLBACK_COLOR)
        _, upr = compute_pixel_diff_ratio(src, rnd)
        assert upr == pytest.approx(0.25)


class TestVarianceDrivenCrops:
    def test_generates_crops_for_different_images(self):
        src = Image.new("RGB", (40, 40), (255, 0, 0))
        rnd = Image.new("RGB", (40, 40), (0, 0, 255))
        crops = variance_driven_crops(src, rnd, n=4, zoom=3)
        assert len(crops) > 0
        for crop_img, region in crops:
            assert isinstance(crop_img, Image.Image)
            assert "x1" in region
            assert "diff_score" in region

    def test_returns_empty_for_tiny_images(self):
        src = Image.new("RGB", (4, 4), (255, 0, 0))
        rnd = Image.new("RGB", (4, 4), (0, 0, 255))
        # win_size = max(4,4)//4 = 1, which is < 2
        crops = variance_driven_crops(src, rnd)
        assert crops == []

    def test_elongated_image_produces_crops(self):
        """100x20 images (banner-like) should still produce crops."""
        src = Image.new("RGB", (100, 20), (255, 0, 0))
        rnd = Image.new("RGB", (100, 20), (0, 0, 255))
        crops = variance_driven_crops(src, rnd, n=4, zoom=3)
        assert len(crops) > 0

    def test_fallback_regions_ignored_in_crops(self):
        """Crops should focus on real diffs, not FALLBACK_COLOR regions."""
        # Left half: render is fallback (magenta), right half: real color diff
        src = Image.new("RGB", (40, 40), (128, 128, 128))
        rnd = Image.new("RGB", (40, 40), (128, 128, 128))
        for y in range(40):
            for x in range(20):
                rnd.putpixel((x, y), FALLBACK_COLOR)       # left: fallback
            for x in range(20, 40):
                rnd.putpixel((x, y), (0, 0, 0))            # right: real diff
        crops = variance_driven_crops(src, rnd, n=2, zoom=2)
        assert len(crops) > 0
        # Top crop should be in the right half (real diff), not left (fallback)
        top_region = crops[0][1]
        assert top_region["x1"] >= 10  # should not be anchored in far left

    def test_nms_prevents_overlap(self):
        # Create image with two distinct high-diff quadrants
        src = Image.new("RGB", (40, 40), (128, 128, 128))
        rnd = Image.new("RGB", (40, 40), (128, 128, 128))
        # Make top-left and bottom-right quadrants differ
        for x in range(20):
            for y in range(20):
                rnd.putpixel((x, y), (0, 0, 0))
                rnd.putpixel((x + 20, y + 20), (255, 255, 255))
        crops = variance_driven_crops(src, rnd, n=4, zoom=2)
        # Should get at most 4 non-overlapping regions
        assert len(crops) <= 4
        if len(crops) >= 2:
            r0 = crops[0][1]
            r1 = crops[1][1]
            # Regions should not fully overlap
            assert not (r0["x1"] == r1["x1"] and r0["y1"] == r1["y1"])


class TestFidelityCLI:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, "-m", "kasukabe.fidelity", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--workspace" in result.stdout
        assert "--source-image" in result.stdout

    def test_end_to_end(self, tmp_path):
        """Full CLI run with a small blueprint and source image."""
        # Create source image
        source = Image.new("RGB", (100, 80), (200, 100, 50))
        source_path = tmp_path / "source.png"
        source.save(source_path)

        # Create blueprint
        workspace = tmp_path / "ws"
        workspace.mkdir()
        bp = _make_blueprint(
            [
                {"x": x, "y": y, "z": 0, "block": "minecraft:orange_concrete"}
                for x in range(10)
                for y in range(8)
            ],
            {"x": 10, "y": 8, "z": 1},
        )
        (workspace / "blueprint.json").write_text(json.dumps(bp))

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kasukabe.fidelity",
                "--workspace",
                str(workspace),
                "--source-image",
                str(source_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

        # Check output files exist
        assert (workspace / "fidelity_render.png").exists()
        assert (workspace / "fidelity_comparison.png").exists()
        assert (workspace / "fidelity_result.json").exists()

        fidelity = json.loads((workspace / "fidelity_result.json").read_text())
        assert "pixel_diff_ratio" in fidelity
        assert 0.0 <= fidelity["pixel_diff_ratio"] <= 1.0
        assert "aspect_ratio_match" in fidelity
        assert 0.0 < fidelity["aspect_ratio_match"] <= 1.0
        assert "unknown_pixel_ratio" in fidelity
        assert 0.0 <= fidelity["unknown_pixel_ratio"] <= 1.0
        assert fidelity["unknown_blocks"] == []
