"""Deterministic pixel-level Minecraft replica from a 2D image.

CLI:
  python -m kasukabe.pixel_replica \\
      --image <path> --workspace <dir> --origin x,y,z \\
      [--size WxH] [--axis xy|xz|yz] [--dither none|fs-linear] \\
      [--fit fit|cover|stretch] [--style wood-only|stone-only|concrete-only|grayscale|none] \\
      [--backlight none|light_block|glowstone_row|auto] \\
      [--force-flat] [--allow-translucent --backdrop <block>] \\
      [--region X1,Y1,X2,Y2] [--confirm-preview]

Produces (written atomically under workspace):
  - blueprint.json
  - preview.png
  - gamut_report.json
  - replica_trace.json
  - lighting_recommendation.json
  - pixel_replica_done.json      (commit marker, last)

On any failure, pixel_replica_done.json gets a BLOCKED status with reason + traceback.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from kasukabe.block_palette import (
    BlockConstraint,
    all_entries,
    get_entry,
    list_palette,
)
from kasukabe.color_engine import (
    PaletteIndex,
    dither_fs_linear,
    gamma_correct_resize,
    gamut_coverage,
)

# ── World bounds (Minecraft 1.21 Java) ──────────────────────────────────────
MIN_Y = -64
MAX_Y = 319   # inclusive; 320 is the ceiling wall above build limit

# Intent-guard filename patterns.
# Use explicit word-like boundaries (start-of-string, end-of-string, or non-letter)
# so "house_front.png" still triggers "house" (the \w \b approach fails because
# '_' is a word char and would suppress the boundary).
_INTENT_PATTERNS = re.compile(
    r"(?:^|[^a-zA-Z])(house|castle|building|room|office)(?:[^a-zA-Z]|$)",
    re.I,
)

# Argparse defaults; must stay in sync with main()'s parser.
_REGION_INHERITED_DEFAULTS: dict[str, object] = {
    "backlight": "auto",
    "style": "none",
    "fit": "fit",
    "allow_translucent": False,
    "backdrop": "",
}


# ── Utility: atomic write ───────────────────────────────────────────────────
def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _atomic_write_json(path: Path, obj) -> None:
    _atomic_write_bytes(path, json.dumps(obj, indent=2).encode("utf-8"))


def _atomic_write_image(path: Path, img: Image.Image) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    # PIL needs an explicit format when the extension is ambiguous (".png.tmp").
    fmt = path.suffix.lstrip(".").upper() or "PNG"
    if fmt == "JPG":
        fmt = "JPEG"
    img.save(tmp, format=fmt)
    os.replace(tmp, path)


# ── Palette filtering (--style + --allow-translucent) ───────────────────────
_STYLE_WHITELIST_SUBSTR = {
    "wood-only":     ["_log", "_wood", "_planks", "_hyphae", "stripped_"],
    "stone-only":    ["stone", "deepslate", "cobble", "granite", "andesite",
                      "diorite", "basalt", "blackstone", "tuff", "calcite", "sandstone"],
    "concrete-only": ["_concrete"],  # excludes concrete_powder via constraint filter below
}


def _filter_palette(style: str, allow_translucent: bool) -> list:
    include = BlockConstraint.NONE
    if allow_translucent:
        include |= BlockConstraint.TRANSLUCENT
    entries = list_palette(face="side", include=include)
    if style == "wood-only":
        subs = _STYLE_WHITELIST_SUBSTR["wood-only"]
        entries = [e for e in entries if any(s in e.block_id for s in subs)]
    elif style == "stone-only":
        subs = _STYLE_WHITELIST_SUBSTR["stone-only"]
        entries = [e for e in entries if any(s in e.block_id for s in subs)]
    elif style == "concrete-only":
        # strict: match "_concrete" but not "_concrete_powder"
        entries = [e for e in entries if "_concrete" in e.block_id and "powder" not in e.block_id]
    elif style == "grayscale":
        entries = [e for e in entries if _is_grayscale(e.effective_rgb("side"))]
    elif style == "none":
        pass
    else:
        raise ValueError(f"unknown --style: {style}")
    if not entries:
        raise ValueError(f"palette filter yielded 0 entries for style={style!r}, allow_translucent={allow_translucent}")
    return entries


def _is_grayscale(rgb, tol: int = 12) -> bool:
    r, g, b = rgb
    return max(r, g, b) - min(r, g, b) <= tol


# ── Axis → coordinate mapping ───────────────────────────────────────────────
# image coords: (u, v) with u∈[0,W), v∈[0,H), v=0 at top of image.
# world rel coords: (x, y, z), y=0 at bottom.
def _axis_to_rel(axis: str, u: int, v: int, h: int) -> tuple[int, int, int]:
    if axis == "xy":
        # wall mural facing -Z; looking at it from south: u -> +x, v-top -> +y
        return (u, h - 1 - v, 0)
    if axis == "xz":
        # ground mural; u -> +x, v-top -> nearer +z when viewed from above
        return (u, 0, h - 1 - v)
    if axis == "yz":
        # wall mural facing -X; u -> +z, v-top -> +y
        return (0, h - 1 - v, u)
    raise ValueError(f"unknown axis {axis!r}")


def _axis_view_face(axis: str) -> str:
    return {"xy": "side", "xz": "top", "yz": "side"}[axis]


# ── Backlight ───────────────────────────────────────────────────────────────
def _decide_backlight(mode: str, origin_y: int) -> str:
    if mode in ("none", "light_block", "glowstone_row"):
        return mode
    # auto
    if origin_y < 50:
        return "light_block"
    return "none"


def _lighting_recommendation(origin_y: int, user_choice: str) -> dict:
    recommended = "light_block" if origin_y < 50 else "none"
    return {
        "recommended_backlight": recommended,
        "user_choice": user_choice,
        "reason": (
            f"origin.y={origin_y}, below daylight threshold 50 → recommend light_block"
            if origin_y < 50
            else f"origin.y={origin_y}, above daylight threshold 50 → ambient sky light sufficient"
        ),
        "ambient_checks": {
            "sky_exposed": origin_y >= 50,  # best-effort static heuristic; no world query Phase 1
            "y_below_ground": max(0, 60 - origin_y),
        },
        "alternative_options": ["none", "light_block", "glowstone_row"],
    }


def _backlight_blocks(
    backlight: str,
    axis: str,
    w: int,
    h: int,
) -> tuple[list[dict], dict]:
    """Return (extra_block_entries, actual_footprint).

    actual_footprint is {w, h} possibly expanded when backlight extends the mural.
    """
    extras: list[dict] = []
    footprint = {"w": w, "h": h}
    if backlight == "none":
        return extras, footprint
    if backlight == "light_block":
        # light_block is invisible; place behind mural plane every 5x5.
        for vv in range(0, h, 5):
            for uu in range(0, w, 5):
                if axis == "xy":
                    x, y, z = uu, h - 1 - vv, 1   # behind plane z=0
                elif axis == "xz":
                    x, y, z = uu, -1, h - 1 - vv  # below ground plane
                else:  # yz
                    x, y, z = 1, h - 1 - vv, uu
                extras.append({"x": x, "y": y, "z": z, "block": "minecraft:light[level=15]"})
        return extras, footprint
    if backlight == "glowstone_row":
        # top + bottom rows of glowstone in-plane, expanding footprint by H+2 along the "up" axis.
        for uu in range(w):
            for side_y in (-1, h):
                if axis == "xy":
                    x, y, z = uu, side_y, 0
                elif axis == "xz":
                    # "top/bottom" for a floor mural means in front/behind along +z
                    x, y, z = uu, 0, (h if side_y == h else -1)
                else:  # yz
                    x, y, z = 0, side_y, uu
                extras.append({"x": x, "y": y, "z": z, "block": "minecraft:glowstone"})
        footprint = {"w": w, "h": h + 2}
        return extras, footprint
    raise ValueError(f"unknown backlight mode {backlight!r}")


# ── Main-plane predicate (separates mural pixels from extras) ───────────────
def _is_main_plane(b: dict, axis: str, w: int, h: int) -> bool:
    """True iff block lies on the mural pixel plane (not a backlight/backdrop extra).

    Used by region merge to drop stale extras before regenerating them.
    """
    if axis == "xy":
        return b.get("z", 0) == 0 and 0 <= b["x"] < w and 0 <= b["y"] < h
    if axis == "xz":
        return b.get("y", 0) == 0 and 0 <= b["x"] < w and 0 <= b["z"] < h
    # yz
    return b.get("x", 0) == 0 and 0 <= b["z"] < w and 0 <= b["y"] < h


# ── Fit strategies for --size ───────────────────────────────────────────────
def _resize_for_fit(img: Image.Image, target: tuple[int, int], fit: str) -> Image.Image:
    tw, th = target
    if fit == "stretch":
        return gamma_correct_resize(img, (tw, th))
    w, h = img.size
    src_ar = w / h
    tgt_ar = tw / th
    if fit == "fit":
        # fit inside target; pad with black if needed
        if src_ar >= tgt_ar:
            nw, nh = tw, max(1, round(tw / src_ar))
        else:
            nw, nh = max(1, round(th * src_ar)), th
        resized = gamma_correct_resize(img, (nw, nh))
        canvas = Image.new("RGB", (tw, th), (0, 0, 0))
        canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
        return canvas
    if fit == "cover":
        # cover target; crop center
        if src_ar >= tgt_ar:
            nw, nh = max(1, round(th * src_ar)), th
        else:
            nw, nh = tw, max(1, round(tw / src_ar))
        resized = gamma_correct_resize(img, (nw, nh))
        left = (nw - tw) // 2
        top = (nh - th) // 2
        return resized.crop((left, top, left + tw, top + th))
    raise ValueError(f"unknown --fit {fit!r}")


# ── Core pipeline ───────────────────────────────────────────────────────────
def _run(args: argparse.Namespace, workspace: Path) -> dict:
    done_marker = workspace / "pixel_replica_done.json"
    workspace.mkdir(parents=True, exist_ok=True)

    # 1. Parse + validate origin/size/axis ------------------------------------
    ox, oy, oz = [int(v) for v in args.origin.split(",")]
    axis = args.axis
    if args.size:
        m = re.match(r"^(\d+)x(\d+)(?:x(\d+))?$", args.size)
        if not m:
            raise ValueError(f"--size must be WxH (got {args.size!r})")
        if m.group(3):
            print(f"[pixel_replica] WARN: Phase 1 is 2D; ignoring L={m.group(3)}", file=sys.stderr)
        target_w, target_h = int(m.group(1)), int(m.group(2))
    else:
        target_w = target_h = 0  # auto

    # 1.5 Region preflight: inherit dims/style from existing blueprint --------
    existing = None
    if args.region:
        existing_bp_path = workspace / "blueprint.json"
        if not existing_bp_path.is_file():
            raise ValueError(f"--region requires existing {existing_bp_path}")
        existing = json.loads(existing_bp_path.read_text())
        em = existing.get("meta", {})
        overridden: list[str] = []

        # axis: hard-error on mismatch (different axis = different geometry)
        existing_axis = em.get("axis")
        if existing_axis and existing_axis != axis:
            raise ValueError(
                f"--region must inherit --axis {existing_axis!r} (got {axis!r})"
            )

        # size: inherit from mural_footprint (fallback actual_footprint for old blueprints)
        mural_fp = em.get("mural_footprint") or em.get("actual_footprint")
        if mural_fp:
            inherited_w, inherited_h = int(mural_fp["w"]), int(mural_fp["h"])
            if args.size and (target_w, target_h) != (inherited_w, inherited_h):
                overridden.append(
                    f"--size ({target_w}x{target_h} → {inherited_w}x{inherited_h})"
                )
            target_w, target_h = inherited_w, inherited_h

        # Inherit palette/structure; silent when user didn't override, WARN otherwise.
        for meta_key, attr_name, cli_name in (
            ("backlight", "backlight", "--backlight"),
            ("style", "style", "--style"),
            ("fit", "fit", "--fit"),
            ("allow_translucent", "allow_translucent", "--allow-translucent"),
            ("backdrop", "backdrop", "--backdrop"),
        ):
            stored = em.get(meta_key)
            if stored is None:
                continue
            current = getattr(args, attr_name)
            if current == stored:
                continue
            # Silent inherit when user didn't explicitly pass a different value.
            if current == _REGION_INHERITED_DEFAULTS[attr_name]:
                setattr(args, attr_name, stored)
                continue
            # User explicitly passed a divergent value — override + WARN.
            overridden.append(f"{cli_name} ({current!r} → {stored!r})")
            setattr(args, attr_name, stored)

        if overridden:
            print(
                "[pixel_replica] WARN: region mode inherits from existing blueprint; "
                "overriding: " + ", ".join(overridden),
                file=sys.stderr,
            )

    # 2. Read + exif-correct + resize ----------------------------------------
    img = Image.open(args.image)
    img = ImageOps.exif_transpose(img).convert("RGB")
    src_w, src_h = img.size

    # 3. Intent guard --------------------------------------------------------
    # Skip in region mode: existing blueprint already passed guard.
    if not args.force_flat and existing is None:
        filename_match = bool(_INTENT_PATTERNS.search(Path(args.image).stem))
        aspect = src_w / max(1, src_h)
        aspect_square = 0.9 <= aspect <= 1.1
        if filename_match or aspect_square:
            why = []
            if filename_match:
                why.append("filename suggests architecture (house/castle/building/...)")
            if aspect_square:
                why.append(f"aspect ratio {aspect:.2f} in [0.9, 1.1]")
            raise ValueError(
                "intent guard triggered (" + "; ".join(why) + "). "
                "Pass --force-flat if the input really is a flat 2D mural/pixel art."
            )

    if target_w == 0 or target_h == 0:
        if existing is not None:
            raise ValueError(
                "--region needs blueprint.meta.mural_footprint (or actual_footprint) "
                "to inherit mural dims, or --size WxH to override. This blueprint "
                "predates those fields — re-run the full build to regenerate it, "
                "or pass --size explicitly."
            )
        # Auto-size: default to source dimensions clamped to [8, 256]
        target_w = max(8, min(256, src_w))
        target_h = max(8, min(256, src_h))

    # World bounds check
    if oy < MIN_Y or oy + target_h > MAX_Y + 1:
        raise ValueError(
            f"mural Y range [{oy}, {oy + target_h - 1}] exceeds world bounds [{MIN_Y}, {MAX_Y}]"
        )

    # 4. Map-art hint --------------------------------------------------------
    if (target_w, target_h) == (128, 128):
        print("[pixel_replica] NOTE: 128x128 detected — consider Minecraft map art tools "
              "(MapArtCraft, Rebane's Map-art Helper) for potentially higher fidelity.", file=sys.stderr)

    # 5. (Biome check skipped — BIOME_TINTED blocks are filtered from palette in Phase 1)

    # 6. Select view face + build palette index ------------------------------
    view_face = _axis_view_face(axis)
    entries = _filter_palette(args.style, args.allow_translucent)
    palette = PaletteIndex(entries, view_face=view_face)

    # Backdrop: when translucent allowed, require --backdrop + validate it
    backdrop_block = None
    if args.allow_translucent:
        if not args.backdrop:
            raise ValueError("--allow-translucent requires --backdrop <block_id>")
        if not get_entry(args.backdrop):
            raise ValueError(f"--backdrop {args.backdrop!r} not in palette")
        backdrop_block = args.backdrop

    # 7. Resize image to target footprint -----------------------------------
    img_resized = _resize_for_fit(img, (target_w, target_h), args.fit)
    pixels_srgb = np.asarray(img_resized, dtype=np.float64) / 255.0  # (H, W, 3)

    # 8. Region mode vs full mode -------------------------------------------
    if args.region:
        # --region X1,Y1,X2,Y2 — re-quantize just this sub-rect, merge with existing blueprint
        rm = re.match(r"^(\d+),(\d+),(\d+),(\d+)$", args.region)
        if not rm:
            raise ValueError("--region must be X1,Y1,X2,Y2 (image-pixel coords)")
        x1, y1, x2, y2 = [int(v) for v in rm.groups()]
        if not (0 <= x1 < x2 <= target_w and 0 <= y1 < y2 <= target_h):
            raise ValueError(f"--region out of bounds for {target_w}x{target_h}")
        region_area = (x2 - x1) * (y2 - y1)
        if region_area > 500:
            print(f"[pixel_replica] WARN: region area {region_area} > 500 — consider full rebuild", file=sys.stderr)
    else:
        x1, y1, x2, y2 = 0, 0, target_w, target_h

    sub = pixels_srgb[y1:y2, x1:x2]

    # 9. Quantize -----------------------------------------------------------
    if args.dither == "fs-linear":
        idx_arr = dither_fs_linear(sub, palette)  # (h, w)
    elif args.dither == "none":
        idx_arr = palette.nearest(sub)
    else:
        raise ValueError(f"unknown --dither {args.dither!r}")

    # 10. Build block list + constraints trace -----------------------------
    palette_freq: collections.Counter = collections.Counter()
    unknown_blocks: set[str] = set()
    pixel_blocks: list[dict] = []
    h_sub, w_sub = idx_arr.shape
    for v_rel in range(h_sub):
        for u_rel in range(w_sub):
            idx = int(idx_arr[v_rel, u_rel])
            entry = palette.entries[idx]
            if not get_entry(entry.block_id):
                unknown_blocks.add(entry.block_id)
            palette_freq[entry.block_id] += 1
            u_abs = x1 + u_rel
            v_abs = y1 + v_rel
            x, y, z = _axis_to_rel(axis, u_abs, v_abs, target_h)
            pixel_blocks.append({"x": x, "y": y, "z": z, "block": entry.block_id})

    # 11. Backlight + backdrop ------------------------------------------------
    backlight_mode = _decide_backlight(args.backlight, oy)
    extra_blocks, actual_fp = _backlight_blocks(backlight_mode, axis, target_w, target_h)

    if backdrop_block:
        # Put backdrop one block behind the mural plane
        for v_abs in range(target_h):
            for u_abs in range(target_w):
                x, y, z = _axis_to_rel(axis, u_abs, v_abs, target_h)
                if axis == "xy":
                    z += 1
                elif axis == "xz":
                    y -= 1
                else:  # yz
                    x += 1
                extra_blocks.append({"x": x, "y": y, "z": z, "block": backdrop_block})

    # 12. Blueprint assembly (region-mode merges into existing) --------------
    if existing is not None:
        # Replace blocks in the region, keep main-plane pixels outside it.
        # Drop ALL extras (backlight/backdrop/glowstone_row) — they get
        # deterministically regenerated from extra_blocks below, so merging in
        # the old ones would double-count them on each region retry.
        def _in_region(b: dict) -> bool:
            # Work in image coords: reverse the axis mapping to test the sub-rect.
            if axis == "xy":
                u, v = b["x"], target_h - 1 - b["y"]
                return (x1 <= u < x2) and (y1 <= v < y2) and b["z"] == 0
            if axis == "xz":
                u, v = b["x"], target_h - 1 - b["z"]
                return (x1 <= u < x2) and (y1 <= v < y2) and b["y"] == 0
            # yz
            u, v = b["z"], target_h - 1 - b["y"]
            return (x1 <= u < x2) and (y1 <= v < y2) and b["x"] == 0

        kept = [
            b for b in existing["blocks"]
            if _is_main_plane(b, axis, target_w, target_h) and not _in_region(b)
        ]
        blocks = kept + pixel_blocks + extra_blocks
        meta = existing["meta"]
        meta["size"] = {"x": target_w, "y": actual_fp["h"], "z": 1}
        meta["actual_footprint"] = actual_fp
        meta["mural_footprint"] = {"w": target_w, "h": target_h}
        meta["backlight"] = backlight_mode
        meta["style"] = args.style
        meta["fit"] = args.fit
        meta["allow_translucent"] = args.allow_translucent
        meta["backdrop"] = args.backdrop
        meta["deterministic"] = True
    else:
        blocks = pixel_blocks + extra_blocks
        meta = {
            "name": f"pixel_mural_{target_w}x{target_h}",
            "size": {"x": target_w, "y": actual_fp["h"], "z": 1},
            "origin": {"x": ox, "y": oy, "z": oz},
            "style": args.style,
            "fit": args.fit,
            "allow_translucent": args.allow_translucent,
            "backdrop": args.backdrop,
            "confidence": 1.0,
            "deterministic": True,
            "axis": axis,
            "view_face": view_face,
            "backlight": backlight_mode,
            "actual_footprint": actual_fp,
            "mural_footprint": {"w": target_w, "h": target_h},
            "source_image": os.fspath(Path(args.image).resolve()),
        }

    blueprint = {
        "meta": meta,
        "materials": [
            {"block": b, "count": c, "usage": "mural"}
            for b, c in palette_freq.most_common()
        ],
        "layers": [{"y_offset": y, "description": "mural row", "primary_block": ""} for y in range(meta["size"]["y"])],
        "blocks": blocks,
    }

    _atomic_write_json(workspace / "blueprint.json", blueprint)

    # 13. Preview render -----------------------------------------------------
    preview_img = _render_preview(blueprint)
    _atomic_write_image(workspace / "preview.png", preview_img)

    # 14. Gamut report -------------------------------------------------------
    gamut = gamut_coverage(pixels_srgb.reshape(-1, 3), palette, threshold_de=15.0)
    gamut["actual_footprint"] = actual_fp
    gamut["palette_size"] = len(palette)
    gamut["style"] = args.style
    if gamut["in_gamut_ratio"] < 0.7:
        print(f"[pixel_replica] WARN: in_gamut_ratio={gamut['in_gamut_ratio']:.2f} < 0.7 — palette may be too narrow for this image", file=sys.stderr)
    _atomic_write_json(workspace / "gamut_report.json", gamut)

    # 15. Replica trace ------------------------------------------------------
    trace = _build_trace(pixels_srgb, idx_arr, palette, palette_freq, unknown_blocks, args)
    _atomic_write_json(workspace / "replica_trace.json", trace)

    # 16. Lighting recommendation -------------------------------------------
    _atomic_write_json(
        workspace / "lighting_recommendation.json",
        _lighting_recommendation(oy, backlight_mode),
    )

    # 17. Commit marker (last) ----------------------------------------------
    summary = {
        "status": "DONE",
        "block_count": len(blocks),
        "pixel_count": target_w * target_h,
        "actual_footprint": actual_fp,
        "axis": axis,
        "view_face": view_face,
        "backlight": backlight_mode,
        "in_gamut_ratio": gamut["in_gamut_ratio"],
        "mean_de": gamut["mean_de"],
        "palette_size": len(palette),
        "unknown_blocks": sorted(unknown_blocks),
    }
    _atomic_write_json(done_marker, summary)
    return summary


def _render_preview(blueprint: dict) -> Image.Image:
    """Render mural blocks to an RGB preview image using side_rgb for all entries."""
    meta = blueprint["meta"]
    axis = meta.get("axis", "xy")
    view = meta.get("view_face", "side")
    w = meta["size"]["x"]
    h = meta["size"]["y"]
    img = Image.new("RGB", (w, h), (0, 0, 0))
    for b in blueprint["blocks"]:
        entry = get_entry(b["block"])
        if entry is None:
            rgb = (255, 0, 255)
        else:
            rgb = entry.effective_rgb(view)
        if axis == "xy":
            u = b["x"]
            v = h - 1 - b["y"]
        elif axis == "xz":
            u = b["x"]
            v = h - 1 - b["z"]
        else:  # yz
            u = b["z"]
            v = h - 1 - b["y"]
        if 0 <= u < w and 0 <= v < h:
            img.putpixel((u, v), rgb)
    return img


def _build_trace(
    pixels_srgb: np.ndarray,
    idx_arr: np.ndarray,
    palette: PaletteIndex,
    palette_freq: collections.Counter,
    unknown_blocks: set[str],
    args: argparse.Namespace,
) -> dict:
    """Sample up to 100 representative pixel decisions for debugging."""
    h, w, _ = pixels_srgb.shape
    n_samples = min(100, h * w)
    # Strided sample so it covers the whole image
    rng = np.linspace(0, h * w - 1, n_samples, dtype=int)
    samples = []
    flat_rgb = (pixels_srgb.reshape(-1, 3) * 255).astype(int)
    flat_idx_shape = idx_arr.shape  # (H', W')
    for r in rng:
        v = int(r // w)
        u = int(r % w)
        # Clamp to region sub-array if region mode resized idx_arr
        if v >= flat_idx_shape[0] or u >= flat_idx_shape[1]:
            continue
        picked = palette.entries[int(idx_arr[v, u])]
        samples.append({
            "pixel": [u, v],
            "src_rgb": flat_rgb[r].tolist(),
            "picked": picked.block_id,
            "picked_rgb": list(picked.effective_rgb(palette.view_face)),
        })
    return {
        "args": {
            "style": args.style,
            "axis": args.axis,
            "dither": args.dither,
            "fit": args.fit,
            "backlight": args.backlight,
            "allow_translucent": args.allow_translucent,
            "region": args.region,
        },
        "palette_size": len(palette),
        "palette_freq": palette_freq.most_common(32),
        "unknown_blocks": sorted(unknown_blocks),
        "samples": samples,
    }


# ── CLI ────────────────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--image", required=True, help="path to source image")
    p.add_argument("--workspace", required=True, help="workspace directory")
    p.add_argument("--origin", required=True, help="x,y,z integers (world coords)")
    p.add_argument("--size", default="", help="WxH (default: auto)")
    p.add_argument("--axis", default="xy", choices=["xy", "xz", "yz"])
    p.add_argument("--dither", default="none", choices=["none", "fs-linear"])
    p.add_argument("--fit", default="fit", choices=["fit", "cover", "stretch"])
    p.add_argument("--style", default="none",
                   choices=["wood-only", "stone-only", "concrete-only", "grayscale", "none"])
    p.add_argument("--backlight", default="auto",
                   choices=["none", "light_block", "glowstone_row", "auto"])
    p.add_argument("--force-flat", action="store_true", help="bypass intent guard")
    p.add_argument("--allow-translucent", action="store_true")
    p.add_argument("--backdrop", default="", help="required with --allow-translucent")
    p.add_argument("--region", default="", help="X1,Y1,X2,Y2 image-pixel sub-rect")
    p.add_argument("--confirm-preview", action="store_true", help="informational; handled by Skill")
    args = p.parse_args()

    workspace = Path(args.workspace)
    done_marker = workspace / "pixel_replica_done.json"

    try:
        summary = _run(args, workspace)
        print(f"[pixel_replica] DONE — {summary['block_count']} blocks, in_gamut_ratio={summary['in_gamut_ratio']:.3f}")
        return 0
    except Exception as e:  # noqa: BLE001
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(done_marker, {
                "status": "BLOCKED",
                "reason": str(e),
                "traceback": traceback.format_exc(),
            })
        except Exception:
            pass  # last-ditch: don't compound the failure
        print(f"[pixel_replica] BLOCKED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
