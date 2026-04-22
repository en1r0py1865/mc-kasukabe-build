"""Blueprint fidelity checker — renders blueprint to image, compares with source.

CLI: python -m kasukabe.fidelity --workspace <WS> --source-image <PATH>

Produces:
  - fidelity_render.png      — blueprint front-face projection
  - fidelity_comparison.png   — side-by-side [source | render] at viewable size
  - fidelity_crop_0..N.png    — variance-driven high-difference region crops
  - fidelity_result.json      — quantitative results + metadata
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image

from kasukabe.block_palette import FALLBACK_COLOR, get_color


# ── Rendering ────────────────────────────────────────────────────────────────


def render_blueprint(
    blueprint: dict, *, axis: str | None = None
) -> tuple[Image.Image, list[str]]:
    """Render blueprint to a 2D image, axis-aware.

    The "front face" per axis matches the viewer position that pixel_replica
    assumes when it places backlight/backdrop extras:

    - axis="xy" (wall, default for kasukabe-build 3D blueprints): viewer at
      z<0. Project (x, y); the visible block per cell is the one with the
      SMALLEST z (backdrop/light_block sit at z=+1, behind the mural).
    - axis="xz" (floor mural, view_face="top"): viewer above at y>0 looking
      down. Project (x, z); the visible block per cell is the one with the
      LARGEST y (backdrop/light_block sit at y=-1, below the mural).
    - axis="yz" (side wall, view_face="side"): viewer at x<0. Project (z, y);
      the visible block per cell is the one with the SMALLEST x
      (backdrop/light_block sit at x=+1, behind the mural).

    If `axis` is None, read `blueprint["meta"].get("axis", "xy")`. Legacy 3D
    blueprints from kasukabe-build have no meta.axis → default "xy" preserves
    the previous behavior byte-for-byte.

    Returns (rendered_image, list_of_unknown_block_ids).
    """
    meta = blueprint["meta"]
    if axis is None:
        axis = meta.get("axis", "xy")

    # Prefer actual_footprint (pixel mural dimensions) when present; else size.
    fp = meta.get("actual_footprint")
    size = meta.get("size", {})
    if axis == "xy":
        w = int(fp["w"]) if fp else int(size.get("x", 0))
        h = int(fp["h"]) if fp else int(size.get("y", 0))
        primary = ("x", "y")
        depth_key = "z"
        depth_sign = 1   # min-z wins (viewer at -z)
    elif axis == "xz":
        w = int(fp["w"]) if fp else int(size.get("x", 0))
        h = int(fp["h"]) if fp else int(size.get("z", 0))
        primary = ("x", "z")
        depth_key = "y"
        depth_sign = -1  # max-y wins (viewer above at +y, looking down)
    elif axis == "yz":
        w = int(fp["w"]) if fp else int(size.get("z", 0))
        h = int(fp["h"]) if fp else int(size.get("y", 0))
        primary = ("z", "y")
        depth_key = "x"
        depth_sign = 1   # min-x wins (viewer at -x)
    else:
        raise ValueError(f"unknown axis {axis!r}; expected xy, xz, or yz")

    img = Image.new("RGB", (w, h), (0, 0, 0))
    unknown: set[str] = set()

    # Group by (u, v). First block seen per cell wins, and we sort so the
    # front-facing block is first: ascending depth_sign * depth.
    grid: dict[tuple[int, int], str] = {}
    u_key, v_key = primary
    for block in sorted(
        blueprint["blocks"],
        key=lambda b: depth_sign * b.get(depth_key, 0),
    ):
        pos = (int(block[u_key]), int(block[v_key]))
        bid = block["block"]
        if pos not in grid and bid != "minecraft:air":
            grid[pos] = bid

    for (u, v), block_id in grid.items():
        color = get_color(block_id)
        if color == FALLBACK_COLOR:
            unknown.add(block_id)
        if 0 <= u < w and 0 <= v < h:
            img.putpixel((u, h - 1 - v), color)  # v-flip: v=0 at bottom

    return img, sorted(unknown)


# ── Comparison helpers ───────────────────────────────────────────────────────


def prepare_comparison(
    source_path: str, render: Image.Image
) -> tuple[Image.Image, float]:
    """Resize source to render dimensions for pixel-level comparison.

    Returns (source_resized, aspect_ratio_match) where aspect_ratio_match
    is min(src_ratio, rnd_ratio) / max(...), 1.0 = identical ratios.
    """
    source = Image.open(source_path).convert("RGB")
    src_ratio = source.width / source.height
    rnd_ratio = render.width / render.height
    ar_match = min(src_ratio, rnd_ratio) / max(src_ratio, rnd_ratio)
    source_resized = source.resize((render.width, render.height), Image.LANCZOS)
    return source_resized, ar_match


def make_comparison_image(
    source_resized: Image.Image, render: Image.Image
) -> Image.Image:
    """Side-by-side [source | render] zoomed to a viewable size."""
    target = min(512, max(render.width, render.height) * 8)
    scale = target / max(render.width, render.height)
    w = max(1, int(render.width * scale))
    h = max(1, int(render.height * scale))
    gap = 4

    src_up = source_resized.resize((w, h), Image.NEAREST)
    rnd_up = render.resize((w, h), Image.NEAREST)

    comp = Image.new("RGB", (w * 2 + gap, h), (128, 128, 128))
    comp.paste(src_up, (0, 0))
    comp.paste(rnd_up, (w + gap, 0))
    return comp


# ── Metrics ──────────────────────────────────────────────────────────────────


def _pixels(img: Image.Image) -> list[tuple[int, int, int]]:
    """Extract pixel tuples from an RGB image's raw bytes."""
    raw = img.tobytes()
    return [
        (raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)
    ]


def compute_pixel_diff_ratio(
    source_resized: Image.Image, render: Image.Image
) -> tuple[float, float]:
    """Per-pixel L2 distance ratio, excluding unknown (FALLBACK_COLOR) pixels.

    Returns (pixel_diff_ratio, unknown_pixel_ratio).
    pixel_diff_ratio: 0.0 = identical, ~1.0 = max difference.
    unknown_pixel_ratio: fraction of render pixels that are FALLBACK_COLOR.
    """
    src_data = _pixels(source_resized)
    rnd_data = _pixels(render)
    if not src_data:
        return 0.0, 0.0
    max_dist = math.sqrt(3 * 255**2)  # ~441.67
    total = 0.0
    counted = 0
    unknown = 0
    for s, r in zip(src_data, rnd_data):
        if r == FALLBACK_COLOR:
            unknown += 1
            continue
        diff = math.sqrt(sum((a - b) ** 2 for a, b in zip(s, r)))
        total += diff / max_dist
        counted += 1
    pdr = total / counted if counted else 0.0
    upr = unknown / len(rnd_data)
    return pdr, upr


# ── Variance-driven crops ───────────────────────────────────────────────────


def _build_diff_map(
    source_resized: Image.Image, render: Image.Image
) -> list[list[float]]:
    """Per-pixel L2 diff as 2D list [row][col].

    Pixels where render == FALLBACK_COLOR are set to 0.0 (masked).
    """
    w, h = render.width, render.height
    src_data = _pixels(source_resized)
    rnd_data = _pixels(render)
    diff_map: list[list[float]] = []
    for row in range(h):
        line: list[float] = []
        for col in range(w):
            idx = row * w + col
            s, r = src_data[idx], rnd_data[idx]
            if r == FALLBACK_COLOR:
                line.append(0.0)
            else:
                d = math.sqrt(sum((a - b) ** 2 for a, b in zip(s, r)))
                line.append(d)
        diff_map.append(line)
    return diff_map


def _build_integral(diff_map: list[list[float]]) -> list[list[float]]:
    """Build integral image (SAT) from diff_map.  Padded +1 in each dim."""
    h = len(diff_map)
    w = len(diff_map[0]) if h else 0
    # integral[i+1][j+1] = sum of diff_map[0..i][0..j]
    integral = [[0.0] * (w + 1) for _ in range(h + 1)]
    for i in range(h):
        for j in range(w):
            integral[i + 1][j + 1] = (
                diff_map[i][j]
                + integral[i][j + 1]
                + integral[i + 1][j]
                - integral[i][j]
            )
    return integral


def _window_sum(
    integral: list[list[float]], y1: int, x1: int, y2: int, x2: int
) -> float:
    """Sum over rectangle [y1, x1, y2, x2] (inclusive) using integral image."""
    return (
        integral[y2 + 1][x2 + 1]
        - integral[y1][x2 + 1]
        - integral[y2 + 1][x1]
        + integral[y1][x1]
    )


def variance_driven_crops(
    source_resized: Image.Image,
    render: Image.Image,
    n: int = 4,
    zoom: int = 3,
) -> list[tuple[Image.Image, dict]]:
    """Top-N high-difference region crops via sliding window + NMS.

    Returns list of (crop_image, region_dict).
    region_dict: {x1, y1, x2, y2, diff_score}.
    """
    w, h = render.width, render.height
    win_size = min(max(w, h) // 4, min(w, h))
    if win_size < 2:
        return []

    diff_map = _build_diff_map(source_resized, render)
    integral = _build_integral(diff_map)

    # Sliding window scores
    candidates: list[tuple[float, int, int]] = []
    for y in range(h - win_size + 1):
        for x in range(w - win_size + 1):
            score = _window_sum(integral, y, x, y + win_size - 1, x + win_size - 1)
            candidates.append((score, x, y))

    if not candidates:
        return []

    candidates.sort(reverse=True)

    # NMS: suppress overlapping windows
    selected: list[tuple[float, int, int]] = []
    for score, x, y in candidates:
        if len(selected) >= n:
            break
        overlap = any(
            abs(x - sx) < win_size and abs(y - sy) < win_size
            for _, sx, sy in selected
        )
        if not overlap:
            selected.append((score, x, y))

    # Generate side-by-side crop images
    gap = 2
    crops: list[tuple[Image.Image, dict]] = []
    for score, x, y in selected:
        x2 = min(x + win_size, w)
        y2 = min(y + win_size, h)

        src_crop = source_resized.crop((x, y, x2, y2))
        rnd_crop = render.crop((x, y, x2, y2))

        crop_w = (x2 - x) * zoom
        crop_h = (y2 - y) * zoom
        src_crop = src_crop.resize((crop_w, crop_h), Image.NEAREST)
        rnd_crop = rnd_crop.resize((crop_w, crop_h), Image.NEAREST)

        combined = Image.new("RGB", (crop_w * 2 + gap, crop_h), (128, 128, 128))
        combined.paste(src_crop, (0, 0))
        combined.paste(rnd_crop, (crop_w + gap, 0))

        region = {
            "x1": x,
            "y1": y,
            "x2": x2,
            "y2": y2,
            "diff_score": round(score, 2),
        }
        crops.append((combined, region))

    return crops


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Blueprint fidelity checker — compare blueprint render with source image",
    )
    parser.add_argument("--workspace", required=True, help="Workspace directory path")
    parser.add_argument("--source-image", required=True, help="Path to source image")
    args = parser.parse_args()

    workspace = Path(args.workspace)
    blueprint_path = workspace / "blueprint.json"

    if not blueprint_path.exists():
        print(f"Error: {blueprint_path} not found", file=sys.stderr)
        sys.exit(1)

    source_path = args.source_image
    if not Path(source_path).exists():
        print(f"Error: source image {source_path} not found", file=sys.stderr)
        sys.exit(1)

    blueprint = json.loads(blueprint_path.read_text())
    size = blueprint.get("meta", {}).get("size", {})
    if not size.get("x") or not size.get("y"):
        print(
            f"Error: blueprint has invalid size {size} (x and y must be > 0)",
            file=sys.stderr,
        )
        sys.exit(1)

    # 1. Render blueprint
    render, unknown_blocks = render_blueprint(blueprint)
    render.save(workspace / "fidelity_render.png")

    # 2. Prepare comparison (resize source to render dimensions)
    source_resized, ar_match = prepare_comparison(source_path, render)

    # 3. Side-by-side comparison at viewable size
    comparison = make_comparison_image(source_resized, render)
    comparison.save(workspace / "fidelity_comparison.png")

    # 4. Pixel diff ratio (excludes FALLBACK_COLOR pixels)
    pixel_diff, unknown_ratio = compute_pixel_diff_ratio(source_resized, render)

    # 5. Variance-driven crops
    crops = variance_driven_crops(source_resized, render)
    crop_images: list[str] = []
    crop_regions: list[dict] = []
    for i, (crop_img, region) in enumerate(crops):
        fname = f"fidelity_crop_{i}.png"
        crop_img.save(workspace / fname)
        crop_images.append(fname)
        crop_regions.append(region)

    # 6. Write result JSON
    result = {
        "source_image": str(Path(source_path).resolve()),
        "render_image": "fidelity_render.png",
        "comparison_image": "fidelity_comparison.png",
        "crop_images": crop_images,
        "crop_regions": crop_regions,
        "pixel_diff_ratio": round(pixel_diff, 4),
        "unknown_pixel_ratio": round(unknown_ratio, 4),
        "aspect_ratio_match": round(ar_match, 4),
        "blueprint_size": blueprint["meta"]["size"],
        "unknown_blocks": unknown_blocks,
    }

    result_path = workspace / "fidelity_result.json"
    result_path.write_text(json.dumps(result, indent=2))
    print(f"Fidelity check complete. pixel_diff_ratio={pixel_diff:.4f}")
    print(f"Results: {result_path}")


if __name__ == "__main__":
    main()
