"""Tests for kasukabe.pixel_replica end-to-end (minus the bridge dep)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


def _make_quadrant_image(path: Path, w: int = 32, h: int = 32) -> None:
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[: h // 2, : w // 2] = (255, 0, 0)
    arr[: h // 2, w // 2 :] = (0, 255, 0)
    arr[h // 2 :, : w // 2] = (0, 0, 255)
    arr[h // 2 :, w // 2 :] = (255, 255, 0)
    Image.fromarray(arr).save(path)


def _run_replica(tmp_path: Path, img: Path, *extra: str) -> dict:
    ws = tmp_path / "ws"
    cmd = [
        sys.executable,
        "-m", "kasukabe.pixel_replica",
        "--image", str(img),
        "--workspace", str(ws),
        "--origin", "100,64,200",
        *extra,
    ]
    subprocess.run(cmd, check=False, capture_output=True)
    done = ws / "pixel_replica_done.json"
    assert done.is_file(), f"done marker missing; workspace contents: {list(ws.iterdir()) if ws.is_dir() else 'missing'}"
    return json.loads(done.read_text())


class TestEndToEnd:
    def test_happy_path_writes_all_artifacts(self, tmp_path):
        img = tmp_path / "quad.png"
        _make_quadrant_image(img)
        done = _run_replica(tmp_path, img, "--size", "32x32", "--force-flat")
        assert done["status"] == "DONE"
        assert done["block_count"] == 32 * 32
        ws = tmp_path / "ws"
        for name in (
            "blueprint.json",
            "preview.png",
            "gamut_report.json",
            "replica_trace.json",
            "lighting_recommendation.json",
            "pixel_replica_done.json",
        ):
            assert (ws / name).is_file(), f"missing {name}"

    def test_blueprint_has_deterministic_flag_and_axis(self, tmp_path):
        img = tmp_path / "quad.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32", "--axis", "xy", "--force-flat")
        bp = json.loads((tmp_path / "ws" / "blueprint.json").read_text())
        assert bp["meta"]["deterministic"] is True
        assert bp["meta"]["axis"] == "xy"
        assert bp["meta"]["view_face"] == "side"
        assert bp["meta"]["size"] == {"x": 32, "y": 32, "z": 1}


class TestIntentGuard:
    def test_guard_blocks_square_without_force_flat(self, tmp_path):
        img = tmp_path / "quad.png"
        _make_quadrant_image(img, 32, 32)
        done = _run_replica(tmp_path, img, "--size", "32x32")
        assert done["status"] == "BLOCKED"
        assert "intent guard" in done["reason"]

    def test_guard_blocks_filename_match_even_with_rectangular(self, tmp_path):
        img = tmp_path / "house_front.png"
        _make_quadrant_image(img, 40, 20)   # aspect 2.0 so only filename triggers
        done = _run_replica(tmp_path, img, "--size", "40x20")
        assert done["status"] == "BLOCKED"
        assert "filename" in done["reason"]

    def test_force_flat_bypasses_guard(self, tmp_path):
        img = tmp_path / "portrait.png"
        _make_quadrant_image(img, 32, 32)
        done = _run_replica(tmp_path, img, "--size", "32x32", "--force-flat")
        assert done["status"] == "DONE"


class TestWorldBounds:
    def test_y_below_floor_is_blocked(self, tmp_path):
        img = tmp_path / "p.png"
        _make_quadrant_image(img, 32, 10)
        ws = tmp_path / "ws"
        cmd = [
            sys.executable,
            "-m", "kasukabe.pixel_replica",
            "--image", str(img),
            "--workspace", str(ws),
            "--origin", "100,-100,200",    # below -64
            "--size", "32x10",
            "--force-flat",
        ]
        subprocess.run(cmd, capture_output=True)
        done = json.loads((ws / "pixel_replica_done.json").read_text())
        assert done["status"] == "BLOCKED"
        assert "world bounds" in done["reason"]

    def test_y_above_ceiling_is_blocked(self, tmp_path):
        img = tmp_path / "p.png"
        _make_quadrant_image(img, 32, 10)
        ws = tmp_path / "ws"
        cmd = [
            sys.executable,
            "-m", "kasukabe.pixel_replica",
            "--image", str(img),
            "--workspace", str(ws),
            "--origin", "100,315,200",    # 315 + 10 = 325 > 320
            "--size", "32x10",
            "--force-flat",
        ]
        subprocess.run(cmd, capture_output=True)
        done = json.loads((ws / "pixel_replica_done.json").read_text())
        assert done["status"] == "BLOCKED"


class TestAxisSwitching:
    @pytest.mark.parametrize("axis,expected_face", [("xy", "side"), ("xz", "top"), ("yz", "side")])
    def test_axis_sets_view_face(self, tmp_path, axis, expected_face):
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32", "--axis", axis, "--force-flat")
        bp = json.loads((tmp_path / "ws" / "blueprint.json").read_text())
        assert bp["meta"]["axis"] == axis
        assert bp["meta"]["view_face"] == expected_face


class TestRegionMode:
    def test_region_requires_existing_blueprint(self, tmp_path):
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        done = _run_replica(tmp_path, img, "--size", "32x32", "--region", "4,4,12,12", "--force-flat")
        assert done["status"] == "BLOCKED"

    def test_region_mismatched_axis_blocks(self, tmp_path):
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32", "--axis", "xy", "--force-flat")
        done = _run_replica(
            tmp_path, img, "--size", "32x32", "--axis", "xz",
            "--region", "4,4,12,12", "--force-flat",
        )
        assert done["status"] == "BLOCKED"
        assert "axis" in done["reason"]

    def test_region_retry_succeeds_on_matching_axis(self, tmp_path):
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32", "--axis", "xy", "--force-flat")
        done = _run_replica(
            tmp_path, img, "--size", "32x32", "--axis", "xy",
            "--region", "4,4,12,12", "--force-flat",
        )
        assert done["status"] == "DONE"

    def test_region_retry_preserves_glowstone_without_duplication(self, tmp_path):
        """Backlight extras must not accumulate across region retries."""
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32", "--axis", "xy",
                     "--backlight", "glowstone_row", "--force-flat")
        bp1 = json.loads((tmp_path / "ws" / "blueprint.json").read_text())
        glow1 = [b for b in bp1["blocks"] if b["block"] == "minecraft:glowstone"]
        assert len(glow1) == 32 * 2, f"first run glowstone count {len(glow1)} != 64"

        done = _run_replica(tmp_path, img, "--size", "32x32", "--axis", "xy",
                            "--backlight", "glowstone_row", "--force-flat",
                            "--region", "4,4,12,12")
        assert done["status"] == "DONE"
        bp2 = json.loads((tmp_path / "ws" / "blueprint.json").read_text())
        glow2 = [b for b in bp2["blocks"] if b["block"] == "minecraft:glowstone"]
        assert len(glow2) == 32 * 2, f"glowstone duplicated after region retry: {len(glow2)}"

    def test_region_retry_inherits_size_without_explicit_flag(self, tmp_path):
        """Region retry without --size must inherit dims from existing blueprint."""
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32", "--axis", "xy", "--force-flat")
        bp1 = json.loads((tmp_path / "ws" / "blueprint.json").read_text())
        assert bp1["meta"]["mural_footprint"] == {"w": 32, "h": 32}
        n_blocks_1 = len(bp1["blocks"])

        done = _run_replica(tmp_path, img, "--axis", "xy",
                            "--region", "4,4,12,12", "--force-flat")
        assert done["status"] == "DONE"
        bp2 = json.loads((tmp_path / "ws" / "blueprint.json").read_text())
        assert bp2["meta"]["mural_footprint"] == {"w": 32, "h": 32}
        assert bp2["meta"]["size"] == {"x": 32, "y": 32, "z": 1}
        assert len(bp2["blocks"]) == n_blocks_1, (
            f"block count drifted: {n_blocks_1} -> {len(bp2['blocks'])}"
        )

    def test_region_retry_silently_overrides_conflicting_style(self, tmp_path):
        """Retry with conflicting --style must be overridden + WARN."""
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32", "--style", "concrete-only",
                     "--force-flat")

        ws = tmp_path / "ws"
        cmd = [
            sys.executable, "-m", "kasukabe.pixel_replica",
            "--image", str(img), "--workspace", str(ws),
            "--origin", "100,64,200", "--style", "wood-only",
            "--region", "4,4,12,12", "--force-flat",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        done = json.loads((ws / "pixel_replica_done.json").read_text())
        assert done["status"] == "DONE"

        bp = json.loads((ws / "blueprint.json").read_text())
        assert bp["meta"]["style"] == "concrete-only", (
            f"style should inherit from existing, got {bp['meta']['style']!r}"
        )
        assert "--style" in res.stderr and "wood-only" in res.stderr, (
            f"expected WARN about style override in stderr; got: {res.stderr!r}"
        )
        # Backlight WARN must NOT fire (user didn't pass --backlight).
        assert "--backlight" not in res.stderr, (
            f"spurious --backlight WARN on minimal retry; stderr: {res.stderr!r}"
        )

    def test_region_retry_no_warn_on_minimal_command(self, tmp_path):
        """Minimal retry must emit zero inherit-WARNs, even across non-default stored flags."""
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32",
                     "--style", "concrete-only",
                     "--backlight", "glowstone_row", "--force-flat")

        ws = tmp_path / "ws"
        cmd = [
            sys.executable, "-m", "kasukabe.pixel_replica",
            "--image", str(img), "--workspace", str(ws),
            "--origin", "100,64,200",
            "--region", "4,4,12,12", "--dither", "fs-linear",
            "--force-flat",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        done = json.loads((ws / "pixel_replica_done.json").read_text())
        assert done["status"] == "DONE"

        bp = json.loads((ws / "blueprint.json").read_text())
        assert bp["meta"]["style"] == "concrete-only"
        assert bp["meta"]["backlight"] == "glowstone_row"
        assert bp["meta"]["mural_footprint"] == {"w": 32, "h": 32}

        assert "region mode inherits" not in res.stderr, (
            f"expected no inherit-WARN on minimal retry; stderr: {res.stderr!r}"
        )

    def test_region_retry_overrides_conflicting_backlight(self, tmp_path):
        """Retry with conflicting --backlight must inherit existing (preserve rows)."""
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32",
                     "--backlight", "glowstone_row", "--force-flat")

        done = _run_replica(tmp_path, img, "--size", "32x32",
                            "--backlight", "none",
                            "--region", "4,4,12,12", "--force-flat")
        assert done["status"] == "DONE"
        bp = json.loads((tmp_path / "ws" / "blueprint.json").read_text())
        assert bp["meta"]["backlight"] == "glowstone_row"
        # Glowstone row must still be present (not removed by overridden CLI).
        glow = [b for b in bp["blocks"] if b["block"] == "minecraft:glowstone"]
        assert len(glow) == 32 * 2

    def test_region_retry_errors_on_legacy_blueprint_without_dims(self, tmp_path):
        """Legacy blueprint lacking footprint fields must BLOCK on --region without --size."""
        ws = tmp_path / "ws"
        ws.mkdir()
        legacy_bp = {
            "meta": {"axis": "xy", "origin": {"x": 100, "y": 64, "z": 200}},
            "materials": [], "layers": [], "blocks": [],
        }
        (ws / "blueprint.json").write_text(json.dumps(legacy_bp))

        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        done = _run_replica(tmp_path, img, "--axis", "xy",
                            "--region", "4,4,12,12", "--force-flat")
        assert done["status"] == "BLOCKED"
        assert "mural_footprint" in done["reason"] or "--size" in done["reason"]

    def test_region_retry_with_backdrop_no_duplication(self, tmp_path):
        """Backdrop plane must not accumulate across region retries."""
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32", "--axis", "xy",
                     "--allow-translucent", "--backdrop", "minecraft:white_concrete",
                     "--force-flat")
        bp1 = json.loads((tmp_path / "ws" / "blueprint.json").read_text())
        bd1 = [b for b in bp1["blocks"]
               if b["block"] == "minecraft:white_concrete" and b.get("z") == 1]
        assert len(bd1) == 32 * 32

        _run_replica(tmp_path, img, "--size", "32x32", "--axis", "xy",
                     "--allow-translucent", "--backdrop", "minecraft:white_concrete",
                     "--force-flat", "--region", "4,4,12,12")
        bp2 = json.loads((tmp_path / "ws" / "blueprint.json").read_text())
        bd2 = [b for b in bp2["blocks"]
               if b["block"] == "minecraft:white_concrete" and b.get("z") == 1]
        assert len(bd2) == 32 * 32, f"backdrop duplicated after region retry: {len(bd2)}"


class TestBacklight:
    def test_glowstone_row_expands_footprint(self, tmp_path):
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        done = _run_replica(tmp_path, img, "--size", "32x32", "--backlight", "glowstone_row", "--force-flat")
        assert done["actual_footprint"] == {"w": 32, "h": 34}

    def test_glowstone_row_records_mural_footprint_separately(self, tmp_path):
        """With glowstone_row, actual_footprint is expanded (+2 rows) but
        mural_footprint stays at the pre-backlight mural dims. replica_inspect
        uses mural_footprint to crop the render so pixel_diff_ratio and
        suggested_region_retry stay within the mural area."""
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32", "--backlight", "glowstone_row", "--force-flat")
        bp = json.loads((tmp_path / "ws" / "blueprint.json").read_text())
        assert bp["meta"]["actual_footprint"] == {"w": 32, "h": 34}
        assert bp["meta"]["mural_footprint"] == {"w": 32, "h": 32}

    def test_no_backlight_mural_matches_actual_footprint(self, tmp_path):
        """Without a footprint-extending backlight, mural_footprint and
        actual_footprint agree — the replica_inspect crop is then a no-op."""
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32", "--backlight", "none", "--force-flat")
        bp = json.loads((tmp_path / "ws" / "blueprint.json").read_text())
        assert bp["meta"]["mural_footprint"] == bp["meta"]["actual_footprint"]


class TestReplicaInspectMuralCrop:
    """Regression: replica_inspect must crop the blueprint render to the mural
    region before computing pixel_diff_ratio / variance_driven_crops, so the
    glowstone_row border does not pollute the metric or produce out-of-bounds
    region retry suggestions."""

    def test_crop_extracts_mural_rows_only(self, tmp_path):
        from kasukabe.fidelity import render_blueprint
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32", "--backlight", "glowstone_row", "--force-flat")
        bp = json.loads((tmp_path / "ws" / "blueprint.json").read_text())

        render, _ = render_blueprint(bp)
        assert render.size == (32, 34)  # actual_footprint

        # Mural is at the bottom h_mural rows (v-flip convention).
        mural_fp = bp["meta"]["mural_footprint"]
        w_mural, h_mural = int(mural_fp["w"]), int(mural_fp["h"])
        w_act, h_act = render.size
        render_mural = render.crop((0, h_act - h_mural, w_mural, h_act))
        assert render_mural.size == (32, 32)

        # The top 2 rows of the original render should contain glowstone-colored
        # pixels (and/or unpainted black) that we have just excluded.
        top_strip = render.crop((0, 0, w_mural, h_act - h_mural))
        top_pixels = list(top_strip.getdata())
        # The glowstone row renders to image row 1 (from top). At least one
        # pixel in the excluded strip must differ from the mural's top row.
        mural_top_row = list(render_mural.crop((0, 0, w_mural, 1)).getdata())
        assert top_pixels != mural_top_row * (h_act - h_mural)

    def test_suggested_region_retry_coords_within_mural(self, tmp_path):
        """variance_driven_crops run on the cropped render must emit region
        coords in the 0..h_mural range (not 0..h_actual)."""
        from kasukabe.fidelity import render_blueprint, variance_driven_crops, prepare_comparison
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        _run_replica(tmp_path, img, "--size", "32x32", "--backlight", "glowstone_row", "--force-flat")
        bp = json.loads((tmp_path / "ws" / "blueprint.json").read_text())

        render, _ = render_blueprint(bp)
        mural_fp = bp["meta"]["mural_footprint"]
        w_mural, h_mural = int(mural_fp["w"]), int(mural_fp["h"])
        w_act, h_act = render.size
        render_mural = render.crop((0, h_act - h_mural, w_mural, h_act))

        source_resized, _ = prepare_comparison(str(img), render_mural)
        crops = variance_driven_crops(source_resized, render_mural, n=4, zoom=3)
        for _crop_img, region in crops:
            assert 0 <= region["y1"] < region["y2"] <= h_mural, region
            assert 0 <= region["x1"] < region["x2"] <= w_mural, region

    def test_auto_low_y_recommends_light_block(self, tmp_path):
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        ws = tmp_path / "ws"
        cmd = [
            sys.executable, "-m", "kasukabe.pixel_replica",
            "--image", str(img), "--workspace", str(ws),
            "--origin", "100,40,200", "--size", "32x32",
            "--backlight", "auto", "--force-flat",
        ]
        subprocess.run(cmd, capture_output=True)
        rec = json.loads((ws / "lighting_recommendation.json").read_text())
        assert rec["recommended_backlight"] == "light_block"

    def test_auto_high_y_recommends_none(self, tmp_path):
        img = tmp_path / "p.png"
        _make_quadrant_image(img)
        ws = tmp_path / "ws"
        cmd = [
            sys.executable, "-m", "kasukabe.pixel_replica",
            "--image", str(img), "--workspace", str(ws),
            "--origin", "100,100,200", "--size", "32x32",
            "--backlight", "auto", "--force-flat",
        ]
        subprocess.run(cmd, capture_output=True)
        rec = json.loads((ws / "lighting_recommendation.json").read_text())
        assert rec["recommended_backlight"] == "none"


class TestBiomeTintedFiltered:
    """BIOME_TINTED blocks (grass, leaves, vines) must not appear in Phase 1 output."""

    def test_no_biome_tinted_blocks_selected(self, tmp_path):
        img = tmp_path / "p.png"
        # A green-ish image, likely to pick grass if BIOME_TINTED weren't filtered.
        arr = np.full((32, 32, 3), (120, 180, 60), dtype=np.uint8)
        Image.fromarray(arr).save(img)
        _run_replica(tmp_path, img, "--size", "32x32", "--force-flat")
        bp = json.loads((tmp_path / "ws" / "blueprint.json").read_text())
        forbidden = ("grass_block", "oak_leaves", "vine", "birch_leaves", "jungle_leaves")
        for b in bp["blocks"]:
            for f in forbidden:
                assert f not in b["block"], f"found forbidden {b['block']}"
