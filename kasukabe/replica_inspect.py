"""Deterministic replica inspector — replaces the LLM Inspector for /kasukabe-pixel.

Steps:
1. Sample-verify built blocks against blueprint (via kasukabe.verifier.verify).
2. Re-render blueprint preview, compare to source image, compute pixel_diff_ratio.
3. Identify top-N high-difference crops and map their blueprint sub-rects back
   into image-pixel coordinates for `--region` retry suggestions.
4. Write replica_inspect_done.json.

No LLM calls. No semantic_issues / fix_commands.

CLI:
    python -m kasukabe.replica_inspect --workspace <DIR> --source-image <PATH> \\
        [--origin x,y,z] [--bridge-url URL]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

from kasukabe.fidelity import (
    compute_pixel_diff_ratio,
    prepare_comparison,
    render_blueprint,
    variance_driven_crops,
)
from kasukabe.verifier import verify

_DEFAULT_BRIDGE = os.getenv("KASUKABE_BRIDGE_URL", "http://localhost:3001")


def _atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(json.dumps(obj, indent=2).encode("utf-8"))
    os.replace(tmp, path)


def _crop_region_to_image_pixels(
    crop_region: dict, axis: str, foot_h: int
) -> list[int]:
    """Convert a fidelity crop region (in render coords) back to image-pixel
    (u, v, u+dw, v+dh) for `--region` retry.

    After `fidelity.render_blueprint` became axis-aware, the returned render is
    always the (u, v) mural plane — (x, y) for xy, (x, z) for xz, (z, y) for yz
    — with a v-flip (row = h - 1 - v). Crop regions are already in the same
    (u, v) frame the CLI's `--region` expects, so this is a pass-through.
    """
    return [crop_region["x1"], crop_region["y1"], crop_region["x2"], crop_region["y2"]]


def _run(args: argparse.Namespace, workspace: Path) -> dict:
    bp_path = workspace / "blueprint.json"
    if not bp_path.is_file():
        raise FileNotFoundError(f"missing {bp_path}")
    blueprint = json.loads(bp_path.read_text())

    meta = blueprint["meta"]
    origin_tuple = (
        int(meta["origin"]["x"]),
        int(meta["origin"]["y"]),
        int(meta["origin"]["z"]),
    )
    if args.origin:
        origin_tuple = tuple(int(v) for v in args.origin.split(","))  # type: ignore[assignment]

    # 1. Verify blocks in world vs blueprint ------------------------------
    verify_result = verify(workspace, origin_tuple, bridge_url=args.bridge_url)
    completion_rate = float(verify_result.get("completion_rate", 0.0))

    # 2. Re-render blueprint preview --------------------------------------
    render_img, unknown_ids = render_blueprint(blueprint)

    # Crop render to the mural region, excluding backlight/backdrop borders
    # (e.g. glowstone_row extends actual_footprint.h by 2). The v-flip in
    # render_blueprint places the mural at the bottom h_mural rows of the
    # rendered image, so we crop that rectangle. When no backlight extends
    # the footprint, mural_footprint == actual_footprint and the crop is a
    # no-op. Older blueprints without mural_footprint fall back to the
    # full render (previous behavior).
    mural_fp = meta.get("mural_footprint") or meta.get("actual_footprint")
    if mural_fp:
        w_mural = int(mural_fp["w"])
        h_mural = int(mural_fp["h"])
        w_act, h_act = render_img.size
        render_mural = render_img.crop(
            (0, h_act - h_mural, w_mural, h_act)
        )
    else:
        render_mural = render_img

    # 3. Source-vs-render fidelity ---------------------------------------
    pdr: float = 0.0
    upr: float = 0.0
    suggested_region_retry: list[list] = []
    if args.source_image and Path(args.source_image).is_file():
        source_resized, _ar_match = prepare_comparison(args.source_image, render_mural)
        pdr, upr = compute_pixel_diff_ratio(source_resized, render_mural)

        # Top-N high-difference crops (use them as retry hints).
        # Coords are already in mural frame (same as --region expects) because
        # we operated on render_mural.
        crops = variance_driven_crops(source_resized, render_mural, n=4, zoom=3)
        axis = meta.get("axis", "xy")
        foot_h = render_mural.height
        for _combined_img, region in crops:
            x1, y1, x2, y2 = _crop_region_to_image_pixels(region, axis, foot_h)
            suggested_region_retry.append([x1, y1, x2, y2, "fs-linear"])

    # 4. Gamut (read if earlier step produced it) -------------------------
    gamut_path = workspace / "gamut_report.json"
    gamut_coverage = None
    if gamut_path.is_file():
        try:
            gamut_coverage = float(json.loads(gamut_path.read_text())["in_gamut_ratio"])
        except Exception:
            gamut_coverage = None

    result = {
        "status": "DONE",
        "completion_rate": completion_rate,
        "pixel_diff_ratio": round(pdr, 4),
        "unknown_pixel_ratio": round(upr, 4),
        "gamut_coverage": gamut_coverage,
        "unknown_blocks": unknown_ids,
        "suggested_region_retry": suggested_region_retry,
        "sampled_blocks": int(verify_result.get("sampled_blocks", 0)),
        "correct_blocks": int(verify_result.get("correct_blocks", 0)),
        "error_count": int(verify_result.get("error_count", 0)),
    }
    _atomic_write_json(workspace / "replica_inspect_done.json", result)
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", required=True)
    p.add_argument("--source-image", default="", help="path to source image (for pixel_diff_ratio)")
    p.add_argument("--origin", default="", help="override origin from blueprint (x,y,z)")
    p.add_argument("--bridge-url", default=_DEFAULT_BRIDGE)
    args = p.parse_args()

    workspace = Path(args.workspace)
    done_path = workspace / "replica_inspect_done.json"
    try:
        res = _run(args, workspace)
        print(
            f"[replica_inspect] DONE — completion={res['completion_rate']:.3f} "
            f"pdr={res['pixel_diff_ratio']:.4f} retries={len(res['suggested_region_retry'])}"
        )
        return 0
    except Exception as e:  # noqa: BLE001
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(done_path, {
                "status": "BLOCKED",
                "reason": str(e),
                "traceback": traceback.format_exc(),
            })
        except Exception:
            pass
        print(f"[replica_inspect] BLOCKED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
