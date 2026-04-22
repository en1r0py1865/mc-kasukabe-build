"""Vectorized color engine for pixel-level Minecraft reconstruction.

- sRGB ↔ linear gamma (IEC 61966-2-1)
- sRGB → OKLab (Björn Ottosson, 2020)
- Vectorized CIEDE2000 (Sharma, Wu, Dalal 2005)
- Gamma-correct resize (BOX default — avoids LANCZOS ringing)
- Two-stage nearest palette matching (KDTree candidates + CIEDE2000 rerank)
- Floyd-Steinberg dithering in linear sRGB

Matching space (OKLab + CIEDE2000 on Lab) vs error-diffusion space (linear sRGB)
are intentionally separate. CIEDE2000 is not a metric, so KDTree on Lab is a
candidate-selection heuristic; final ranking is done with CIEDE2000.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

if TYPE_CHECKING:
    from kasukabe.block_palette import BlockEntry


# ══════════════════════════════════════════════════════════════════════════
# Gamma (sRGB ↔ linear)
# ══════════════════════════════════════════════════════════════════════════

def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    """sRGB [0,1] → linear [0,1]. Supports any trailing shape; last axis is RGB."""
    rgb = np.asarray(rgb, dtype=np.float64)
    linear = np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        ((rgb + 0.055) / 1.055) ** 2.4,
    )
    return linear


def linear_to_srgb(rgb_linear: np.ndarray) -> np.ndarray:
    """Linear [0,1] → sRGB [0,1]."""
    rgb_linear = np.asarray(rgb_linear, dtype=np.float64)
    srgb = np.where(
        rgb_linear <= 0.0031308,
        rgb_linear * 12.92,
        1.055 * np.power(np.clip(rgb_linear, 0.0, None), 1.0 / 2.4) - 0.055,
    )
    return np.clip(srgb, 0.0, 1.0)


# ══════════════════════════════════════════════════════════════════════════
# OKLab (Björn Ottosson, 2020)
# ══════════════════════════════════════════════════════════════════════════

_OKLAB_M1 = np.array([
    [0.4122214708, 0.5363325363, 0.0514459929],
    [0.2119034982, 0.6806995451, 0.1073969566],
    [0.0883024619, 0.2817188376, 0.6299787005],
], dtype=np.float64)

_OKLAB_M2 = np.array([
    [0.2104542553,  0.7936177850, -0.0040720468],
    [1.9779984951, -2.4285922050,  0.4505937099],
    [0.0259040371,  0.7827717662, -0.8086757660],
], dtype=np.float64)

_OKLAB_M1_INV = np.linalg.inv(_OKLAB_M1)
_OKLAB_M2_INV = np.linalg.inv(_OKLAB_M2)


def rgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """sRGB [0,1] → OKLab.  Input last-axis=3; output last-axis=3 (L, a, b)."""
    rgb = np.asarray(rgb, dtype=np.float64)
    linear = srgb_to_linear(rgb)
    lms = linear @ _OKLAB_M1.T
    # cbrt handles negatives cleanly; clip to avoid NaN on numerical negatives
    lms_nl = np.cbrt(lms)
    return lms_nl @ _OKLAB_M2.T


def oklab_to_rgb(oklab: np.ndarray) -> np.ndarray:
    """OKLab → sRGB [0,1]."""
    oklab = np.asarray(oklab, dtype=np.float64)
    lms_nl = oklab @ _OKLAB_M2_INV.T
    lms = lms_nl ** 3
    linear = lms @ _OKLAB_M1_INV.T
    return linear_to_srgb(linear)


# ══════════════════════════════════════════════════════════════════════════
# CIEDE2000 (Sharma, Wu, Dalal 2005) — vectorized
# ══════════════════════════════════════════════════════════════════════════
#
# Input: Lab triples in CIE L*a*b* convention.  Note: OKLab and CIE Lab are
# different spaces.  For CIEDE2000 we expect CIE Lab.  We convert sRGB → CIE
# Lab via D65 white.

_XYZ_FROM_LINEAR_RGB = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
], dtype=np.float64)

# D65 reference white (2° observer)
_D65_XN = 0.95047
_D65_YN = 1.00000
_D65_ZN = 1.08883


def _xyz_to_cielab(xyz: np.ndarray) -> np.ndarray:
    """XYZ (D65-normalized) → CIE L*a*b*."""
    x = xyz[..., 0] / _D65_XN
    y = xyz[..., 1] / _D65_YN
    z = xyz[..., 2] / _D65_ZN
    delta = 6.0 / 29.0

    def f(t: np.ndarray) -> np.ndarray:
        return np.where(
            t > delta ** 3,
            np.cbrt(np.clip(t, 0.0, None)),
            t / (3 * delta ** 2) + 4.0 / 29.0,
        )

    fx, fy, fz = f(x), f(y), f(z)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return np.stack([L, a, b], axis=-1)


def rgb_to_cielab(rgb: np.ndarray) -> np.ndarray:
    """sRGB [0,1] → CIE L*a*b* (D65)."""
    rgb = np.asarray(rgb, dtype=np.float64)
    linear = srgb_to_linear(rgb)
    xyz = linear @ _XYZ_FROM_LINEAR_RGB.T
    return _xyz_to_cielab(xyz)


def ciede2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """Vectorized CIEDE2000 (Sharma 2005).

    Inputs: CIE L*a*b* arrays of broadcast-compatible shape with last-axis=3.
    Output: ΔE array with broadcasted shape (no last axis).
    """
    lab1 = np.asarray(lab1, dtype=np.float64)
    lab2 = np.asarray(lab2, dtype=np.float64)
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]

    # Step 1: C'_i, h'_i
    C1 = np.sqrt(a1 * a1 + b1 * b1)
    C2 = np.sqrt(a2 * a2 + b2 * b2)
    C_bar = 0.5 * (C1 + C2)

    G = 0.5 * (1 - np.sqrt(C_bar ** 7 / (C_bar ** 7 + 25.0 ** 7)))
    a1p = (1 + G) * a1
    a2p = (1 + G) * a2

    C1p = np.sqrt(a1p * a1p + b1 * b1)
    C2p = np.sqrt(a2p * a2p + b2 * b2)

    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    # Where C = 0, define h = 0
    h1p = np.where(C1p == 0, 0.0, h1p)
    h2p = np.where(C2p == 0, 0.0, h2p)

    # Step 2: dL, dC, dH
    dLp = L2 - L1
    dCp = C2p - C1p

    # dh'
    dhp = h2p - h1p
    dhp = np.where(C1p * C2p == 0, 0.0, dhp)
    dhp = np.where(dhp > 180.0, dhp - 360.0, dhp)
    dhp = np.where(dhp < -180.0, dhp + 360.0, dhp)

    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp) / 2)

    # Step 3: CIEDE2000
    L_bar_p = 0.5 * (L1 + L2)
    C_bar_p = 0.5 * (C1p + C2p)

    # h_bar_p
    h_sum = h1p + h2p
    h_diff = np.abs(h1p - h2p)
    h_bar_p = np.where(
        C1p * C2p == 0,
        h_sum,
        np.where(
            h_diff <= 180.0,
            h_sum / 2,
            np.where(h_sum < 360.0, (h_sum + 360.0) / 2, (h_sum - 360.0) / 2),
        ),
    )

    T = (
        1
        - 0.17 * np.cos(np.radians(h_bar_p - 30))
        + 0.24 * np.cos(np.radians(2 * h_bar_p))
        + 0.32 * np.cos(np.radians(3 * h_bar_p + 6))
        - 0.20 * np.cos(np.radians(4 * h_bar_p - 63))
    )

    dTheta = 30 * np.exp(-(((h_bar_p - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(C_bar_p ** 7 / (C_bar_p ** 7 + 25.0 ** 7))
    Sl = 1 + (0.015 * (L_bar_p - 50) ** 2) / np.sqrt(20 + (L_bar_p - 50) ** 2)
    Sc = 1 + 0.045 * C_bar_p
    Sh = 1 + 0.015 * C_bar_p * T
    Rt = -np.sin(np.radians(2 * dTheta)) * Rc

    kL = kC = kH = 1.0
    dE = np.sqrt(
        (dLp / (kL * Sl)) ** 2
        + (dCp / (kC * Sc)) ** 2
        + (dHp / (kH * Sh)) ** 2
        + Rt * (dCp / (kC * Sc)) * (dHp / (kH * Sh))
    )
    return dE


# ══════════════════════════════════════════════════════════════════════════
# Gamma-correct resize
# ══════════════════════════════════════════════════════════════════════════

def gamma_correct_resize(
    img: Image.Image,
    size: tuple[int, int],
    resample: Image.Resampling = Image.Resampling.BOX,
) -> Image.Image:
    """Resize with sRGB → linear → resize → sRGB gamma correction.

    Defaults to BOX to avoid LANCZOS ringing on pixel art. Returns an RGB image.
    """
    img = img.convert("RGB")
    arr = np.asarray(img, dtype=np.float64) / 255.0
    linear = srgb_to_linear(arr)
    # Use PIL to do the resize on a normalized float representation.
    # PIL can't resize float directly, so encode linear as 16-bit, resize, decode.
    linear_u16 = (np.clip(linear, 0, 1) * 65535).astype(np.uint16)
    # PIL "I;16" mode is single-channel 16-bit; do per-channel resize.
    resized_channels = []
    for c in range(3):
        channel = Image.fromarray(linear_u16[:, :, c], mode="I;16")
        channel = channel.resize(size, resample)
        resized_channels.append(np.asarray(channel, dtype=np.float64) / 65535.0)
    linear_resized = np.stack(resized_channels, axis=-1)
    srgb_out = linear_to_srgb(linear_resized)
    return Image.fromarray(np.clip(srgb_out * 255, 0, 255).astype(np.uint8), mode="RGB")


# ══════════════════════════════════════════════════════════════════════════
# PaletteIndex — two-stage nearest palette matching
# ══════════════════════════════════════════════════════════════════════════

class PaletteIndex:
    """Two-stage nearest palette matcher.

    Stage 1: KDTree in OKLab space picks top-K candidates (OKLab ~perceptually
             uniform, and KDTree requires a metric — OKLab euclidean is close
             enough for candidate filtering).
    Stage 2: CIEDE2000 on candidates picks the single best match.

    `view_face` selects which of top/side/bottom the BlockEntry exposes.
    """

    def __init__(self, entries: list["BlockEntry"], view_face: str = "side") -> None:
        if not entries:
            raise ValueError("PaletteIndex: empty entries list")
        if view_face not in ("top", "side", "bottom"):
            raise ValueError(f"PaletteIndex: invalid view_face {view_face!r}")

        self.entries = list(entries)
        self.view_face = view_face

        # Build 3 parallel tables: block_ids, sRGB (0-255 int), OKLab, CIE-Lab.
        n = len(self.entries)
        self.block_ids: list[str] = [e.block_id for e in self.entries]
        rgb_srgb = np.zeros((n, 3), dtype=np.float64)
        for i, e in enumerate(self.entries):
            rgb_srgb[i] = e.effective_rgb(view_face)
        rgb_srgb /= 255.0
        self.rgb_srgb = rgb_srgb
        self.oklab = rgb_to_oklab(rgb_srgb)
        self.cielab = rgb_to_cielab(rgb_srgb)
        self._tree = cKDTree(self.oklab)

    def __len__(self) -> int:
        return len(self.entries)

    def nearest(
        self,
        pixels_rgb: np.ndarray,
        top_k: int = 8,
    ) -> np.ndarray:
        """Return best-match block_id index for each pixel.

        Input: pixels_rgb shape (N, 3) or (H, W, 3), values in [0, 255] or [0, 1].
        Output: index array of matching shape (without the RGB axis) into self.entries.
        """
        pixels_rgb = np.asarray(pixels_rgb, dtype=np.float64)
        original_shape = pixels_rgb.shape[:-1]

        # Normalize to [0, 1] if needed
        if pixels_rgb.max(initial=0.0) > 1.5:
            pixels_rgb = pixels_rgb / 255.0

        flat = pixels_rgb.reshape(-1, 3)
        n_palette = len(self.entries)
        k = min(top_k, n_palette)

        # Stage 1: KDTree top-K candidates in OKLab
        query_oklab = rgb_to_oklab(flat)
        _, cand_idx = self._tree.query(query_oklab, k=k)
        if k == 1:
            cand_idx = cand_idx[:, None]

        # Stage 2: CIEDE2000 on candidates
        query_cielab = rgb_to_cielab(flat)                # (P, 3)
        cand_lab = self.cielab[cand_idx]                   # (P, K, 3)
        q_expanded = query_cielab[:, None, :]              # (P, 1, 3)
        de = ciede2000(q_expanded, cand_lab)               # (P, K)
        best_in_cand = np.argmin(de, axis=1)               # (P,)
        best_idx = cand_idx[np.arange(len(flat)), best_in_cand]  # (P,)

        return best_idx.reshape(original_shape)

    def ids_for(self, idx: np.ndarray) -> np.ndarray:
        """Map index array → block_id string array (same shape)."""
        flat = np.asarray(idx).reshape(-1)
        out = np.array([self.block_ids[i] for i in flat], dtype=object)
        return out.reshape(idx.shape)


# ══════════════════════════════════════════════════════════════════════════
# Gamut coverage
# ══════════════════════════════════════════════════════════════════════════

def gamut_coverage(
    pixels_rgb: np.ndarray,
    palette: PaletteIndex,
    threshold_de: float = 15.0,
) -> dict:
    """Report the fraction of pixels whose best-match CIEDE2000 ≤ threshold_de.

    Returns:
      - in_gamut_ratio: pixels with ΔE ≤ threshold / total
      - mean_de: mean ΔE across all pixels
      - max_de: worst-case ΔE
      - p95_de: 95th percentile ΔE
    """
    pixels_rgb = np.asarray(pixels_rgb, dtype=np.float64)
    if pixels_rgb.max(initial=0.0) > 1.5:
        pixels_rgb = pixels_rgb / 255.0
    flat = pixels_rgb.reshape(-1, 3)
    idx = palette.nearest(flat)
    q_lab = rgb_to_cielab(flat)
    best_lab = palette.cielab[idx]
    de = ciede2000(q_lab, best_lab)

    return {
        "in_gamut_ratio": float(np.mean(de <= threshold_de)),
        "mean_de": float(np.mean(de)),
        "max_de": float(np.max(de)) if de.size else 0.0,
        "p95_de": float(np.percentile(de, 95)) if de.size else 0.0,
        "threshold_de": threshold_de,
        "pixel_count": int(flat.shape[0]),
    }


# ══════════════════════════════════════════════════════════════════════════
# Floyd-Steinberg dithering (linear sRGB space)
# ══════════════════════════════════════════════════════════════════════════

def dither_fs_linear(
    img_srgb: np.ndarray,
    palette: PaletteIndex,
) -> np.ndarray:
    """Floyd-Steinberg error diffusion in linear sRGB.

    Input: img_srgb shape (H, W, 3), values [0, 1] or [0, 255].
    Output: index array shape (H, W) into palette.entries.

    Matching is done in CIEDE2000 space (via palette.nearest); error diffusion
    is done in linear sRGB to stay perceptually meaningful without drift.
    """
    arr = np.asarray(img_srgb, dtype=np.float64)
    if arr.max(initial=0.0) > 1.5:
        arr = arr / 255.0

    linear = srgb_to_linear(arr).copy()  # mutable working buffer
    palette_linear = srgb_to_linear(palette.rgb_srgb)  # (N, 3)

    h, w = linear.shape[:2]
    out_idx = np.zeros((h, w), dtype=np.int64)

    for y in range(h):
        for x in range(w):
            old_linear = linear[y, x].copy()
            # Convert back to sRGB for matcher
            old_srgb = linear_to_srgb(old_linear[None, :])[0]
            idx = int(palette.nearest(old_srgb[None, :])[0])
            out_idx[y, x] = idx
            new_linear = palette_linear[idx]
            err = old_linear - new_linear

            # Distribute error: [7 right, 3 bot-left, 5 bot, 1 bot-right] / 16
            if x + 1 < w:
                linear[y, x + 1] += err * (7 / 16)
            if y + 1 < h:
                if x - 1 >= 0:
                    linear[y + 1, x - 1] += err * (3 / 16)
                linear[y + 1, x] += err * (5 / 16)
                if x + 1 < w:
                    linear[y + 1, x + 1] += err * (1 / 16)

    return out_idx
