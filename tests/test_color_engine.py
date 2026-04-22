"""Tests for kasukabe.color_engine.

Coverage:
- sRGB ↔ linear roundtrip <1e-6
- OKLab ↔ sRGB roundtrip <1e-3
- CIEDE2000 matches Sharma 2005 reference pairs (tolerance 1e-3)
- PaletteIndex: single-pixel exact match + batch query
- gamma_correct_resize preserves pure-color patches
- gamut_coverage reports sensible metrics
- dither_fs_linear returns per-pixel indices
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from kasukabe.block_palette import list_palette
from kasukabe.color_engine import (
    PaletteIndex,
    ciede2000,
    dither_fs_linear,
    gamma_correct_resize,
    gamut_coverage,
    linear_to_srgb,
    oklab_to_rgb,
    rgb_to_cielab,
    rgb_to_oklab,
    srgb_to_linear,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestSrgbLinearRoundtrip:
    def test_roundtrip(self):
        rgb = np.array([[0.0, 0.5, 1.0], [0.25, 0.75, 0.9]])
        assert np.allclose(linear_to_srgb(srgb_to_linear(rgb)), rgb, atol=1e-6)

    def test_endpoints(self):
        assert srgb_to_linear(np.array([0.0]))[0] == pytest.approx(0.0)
        assert srgb_to_linear(np.array([1.0]))[0] == pytest.approx(1.0)


class TestOklabRoundtrip:
    def test_roundtrip(self):
        rgb = np.array([[0.1, 0.5, 0.8], [0.9, 0.2, 0.3], [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
        back = oklab_to_rgb(rgb_to_oklab(rgb))
        assert np.allclose(back, rgb, atol=1e-3)

    def test_gray_axis(self):
        # For any sRGB gray, OKLab.a ≈ 0 and OKLab.b ≈ 0
        rgb = np.array([[0.5, 0.5, 0.5]])
        lab = rgb_to_oklab(rgb)
        assert abs(lab[0, 1]) < 1e-3
        assert abs(lab[0, 2]) < 1e-3


class TestSharmaCiede2000:
    @pytest.fixture(scope="class")
    def pairs(self):
        with open(FIXTURES / "sharma_ciede2000.csv") as fh:
            reader = csv.reader(r for r in fh if not r.startswith("#"))
            next(reader)  # header
            return [[float(x) for x in row] for row in reader]

    def test_pairs_match_reference(self, pairs):
        for row in pairs:
            L1, a1, b1, L2, a2, b2, expected = row
            lab1 = np.array([L1, a1, b1])
            lab2 = np.array([L2, a2, b2])
            got = float(ciede2000(lab1, lab2))
            assert abs(got - expected) < 1e-3, f"row={row}  got={got}"

    def test_symmetric(self, pairs):
        L1, a1, b1, L2, a2, b2, _ = pairs[0]
        ab = ciede2000(np.array([L1, a1, b1]), np.array([L2, a2, b2]))
        ba = ciede2000(np.array([L2, a2, b2]), np.array([L1, a1, b1]))
        assert abs(float(ab) - float(ba)) < 1e-6


class TestPaletteIndex:
    def test_exact_match_on_palette_entry(self):
        entries = list_palette(face="side")
        pi = PaletteIndex(entries, view_face="side")
        # Pick a known entry and query its exact sRGB
        e = entries[10]
        rgb = np.array(e.effective_rgb("side"), dtype=np.float64) / 255.0
        idx = int(pi.nearest(rgb[None, :])[0])
        assert entries[idx].block_id == e.block_id

    def test_batch_shape_preserved(self):
        entries = list_palette(face="side")[:30]
        pi = PaletteIndex(entries, view_face="side")
        pixels = np.random.rand(4, 5, 3)
        out = pi.nearest(pixels)
        assert out.shape == (4, 5)

    def test_invalid_view_face(self):
        with pytest.raises(ValueError):
            PaletteIndex(list_palette(face="side")[:5], view_face="front")

    def test_different_view_face_may_pick_different_block(self):
        # Build two indices from the same entries but different view_face.
        # Anisotropic log entries differ between top/side → nearest may differ.
        entries = list_palette(face="side")
        pi_side = PaletteIndex(entries, view_face="side")
        pi_top = PaletteIndex(entries, view_face="top")
        px = np.array([0.4, 0.25, 0.1])
        i_side = int(pi_side.nearest(px[None, :])[0])
        i_top = int(pi_top.nearest(px[None, :])[0])
        # They can legitimately be the same — just verify both return valid indices.
        assert 0 <= i_side < len(entries)
        assert 0 <= i_top < len(entries)


class TestGammaCorrectResize:
    def test_solid_color_preserved(self):
        # 16x16 solid red — after BOX downsample to 4x4, pixels should still be red.
        img = Image.new("RGB", (16, 16), (255, 0, 0))
        out = gamma_correct_resize(img, (4, 4))
        arr = np.asarray(out)
        assert arr.shape == (4, 4, 3)
        # Allow a tiny rounding tolerance
        assert (arr[..., 0] >= 250).all()
        assert (arr[..., 1] <= 5).all()
        assert (arr[..., 2] <= 5).all()

    def test_size_matches_request(self):
        img = Image.new("RGB", (30, 40), (128, 128, 128))
        out = gamma_correct_resize(img, (12, 8))
        assert out.size == (12, 8)


class TestGamutCoverage:
    def test_reports_fields(self):
        entries = list_palette(face="side")[:32]
        pi = PaletteIndex(entries, view_face="side")
        pixels = np.random.rand(100, 3)
        report = gamut_coverage(pixels, pi, threshold_de=20.0)
        for key in ("in_gamut_ratio", "mean_de", "max_de", "p95_de", "threshold_de", "pixel_count"):
            assert key in report
        assert 0.0 <= report["in_gamut_ratio"] <= 1.0
        assert report["pixel_count"] == 100


class TestDitherFsLinear:
    def test_returns_valid_indices(self):
        entries = list_palette(face="side")[:16]
        pi = PaletteIndex(entries, view_face="side")
        img = np.random.rand(8, 8, 3)
        out = dither_fs_linear(img, pi)
        assert out.shape == (8, 8)
        assert (0 <= out).all() and (out < len(entries)).all()
