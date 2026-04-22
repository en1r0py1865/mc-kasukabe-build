"""Minecraft block palette with face-anisotropic colors + placement constraints.

Used by:
- fidelity.py (render_blueprint) — via get_color (returns side_rgb for backward compat)
- color_engine.PaletteIndex (pixel_replica) — via list_palette(face, include)
- scripts/validate_palette.py — validates every block_id is legal in MC 1.21

RGB values are approximate average texture colors from Minecraft Java Edition 1.21.
Block states (axis=y etc.) are kept as distinct entries when the visible face color differs.

Constraints:
- NONE: safe for all use
- GRAVITY: falls if unsupported (sand, gravel, concrete_powder, anvil)
- PHASE_CHANGE: changes form under certain conditions (concrete_powder → concrete near water)
- FRAGILE: breaks easily, not full cube (torch, redstone_wire, cactus, chorus_flower)
- GROWTH: may grow/change over time (saplings, vines, chorus_flower)
- TRANSLUCENT: not opaque (glass, stained glass, ice, honey, slime, tinted glass)
- BIOME_TINTED: color depends on biome (grass_block, leaves, vines, water) — Phase 1 disabled
- WALK_UNSAFE: unsafe to walk on (farmland, magma_block, soul_sand, cobweb)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Flag, auto

FALLBACK_COLOR: tuple[int, int, int] = (255, 0, 255)  # magenta — signals unknown block


class BlockConstraint(Flag):
    NONE = 0
    GRAVITY = auto()
    PHASE_CHANGE = auto()
    FRAGILE = auto()
    GROWTH = auto()
    TRANSLUCENT = auto()
    BIOME_TINTED = auto()
    WALK_UNSAFE = auto()


@dataclass(frozen=True)
class BlockEntry:
    block_id: str                                  # includes block state, e.g. "oak_log[axis=y]"
    top_rgb: tuple[int, int, int]                  # +y face
    side_rgb: tuple[int, int, int]                 # ±x, ±z faces
    bottom_rgb: tuple[int, int, int]               # -y face
    rendered_rgb: dict[str, tuple[int, int, int]] | None = None  # Phase 2: prismarine-viewer renders
    std_rgb: tuple[int, int, int] | None = None    # Phase 2: texture variance
    constraints: BlockConstraint = BlockConstraint.NONE

    def effective_rgb(self, view_face: str) -> tuple[int, int, int]:
        """Return face color by view orientation.

        view_face ∈ {"top", "side", "bottom"}.
        Prefers Phase 2 rendered_rgb when available.
        """
        if self.rendered_rgb and view_face in self.rendered_rgb:
            return self.rendered_rgb[view_face]
        if view_face == "top":
            return self.top_rgb
        if view_face == "bottom":
            return self.bottom_rgb
        return self.side_rgb


# ── Helpers ────────────────────────────────────────────────────────────────


def _u(block_id: str, rgb: tuple[int, int, int], constraints: BlockConstraint = BlockConstraint.NONE) -> BlockEntry:
    """Uniform block — all 6 faces the same color."""
    return BlockEntry(block_id, rgb, rgb, rgb, constraints=constraints)


def _a(
    block_id: str,
    top: tuple[int, int, int],
    side: tuple[int, int, int],
    bottom: tuple[int, int, int] | None = None,
    constraints: BlockConstraint = BlockConstraint.NONE,
) -> BlockEntry:
    """Anisotropic block — distinct top/side/bottom colors."""
    return BlockEntry(block_id, top, side, bottom if bottom is not None else top, constraints=constraints)


# ── Color constants for wood (log sides = bark, top/bottom = rings) ────────

# (bark_rgb, rings_rgb) per species
_WOODS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "oak":       ((109, 85, 51),  (181, 143, 90)),
    "spruce":    ((59, 38, 17),   (138, 103, 61)),
    "birch":     ((215, 215, 215), (223, 206, 156)),
    "jungle":    ((85, 68, 25),   (170, 130, 82)),
    "acacia":    ((103, 96, 86),  (181, 113, 81)),
    "dark_oak":  ((53, 40, 22),   (70, 47, 23)),
    "crimson":   ((93, 26, 30),   (123, 46, 60)),  # nether "stem" with fungus top
    "warped":    ((26, 106, 97),  (56, 128, 112)),
    "mangrove":  ((85, 37, 22),   (120, 54, 41)),
    "cherry":    ((54, 28, 40),   (227, 178, 163)),
    "bamboo":    ((195, 176, 85), (195, 176, 85)),  # bamboo block: uniform
}

# Stripped logs: bark → stripped texture color; top/bottom stays as rings
_STRIPPED: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "oak":       ((188, 152, 98), (197, 160, 102)),
    "spruce":    ((112, 84, 51),  (146, 105, 63)),
    "birch":     ((215, 200, 147), (218, 207, 156)),
    "jungle":    ((174, 135, 100), (182, 141, 105)),
    "acacia":    ((184, 98, 55),  (198, 112, 66)),
    "dark_oak":  ((78, 58, 34),   (91, 66, 36)),
    "crimson":   ((138, 58, 80),  (143, 63, 85)),
    "warped":    ((59, 152, 144), (63, 159, 150)),
    "mangrove":  ((120, 54, 41),  (132, 61, 46)),
    "cherry":    ((195, 148, 136), (205, 156, 142)),
}

# ── Palette entries ────────────────────────────────────────────────────────
# Each list section is grouped for readability.

_ENTRIES: list[BlockEntry] = [
    # ── Concrete (16) — uniform, no constraints ───────────────────────────
    _u("minecraft:white_concrete",       (207, 213, 214)),
    _u("minecraft:orange_concrete",      (224, 97, 1)),
    _u("minecraft:magenta_concrete",     (169, 48, 159)),
    _u("minecraft:light_blue_concrete",  (36, 137, 199)),
    _u("minecraft:yellow_concrete",      (241, 175, 21)),
    _u("minecraft:lime_concrete",        (94, 169, 24)),
    _u("minecraft:pink_concrete",        (214, 101, 143)),
    _u("minecraft:gray_concrete",        (55, 58, 62)),
    _u("minecraft:light_gray_concrete",  (125, 125, 115)),
    _u("minecraft:cyan_concrete",        (21, 119, 136)),
    _u("minecraft:purple_concrete",      (100, 32, 156)),
    _u("minecraft:blue_concrete",        (45, 47, 143)),
    _u("minecraft:brown_concrete",       (96, 60, 32)),
    _u("minecraft:green_concrete",       (73, 91, 36)),
    _u("minecraft:red_concrete",         (142, 33, 33)),
    _u("minecraft:black_concrete",       (8, 10, 15)),

    # ── Concrete Powder (16) — GRAVITY + PHASE_CHANGE ─────────────────────
    _u("minecraft:white_concrete_powder",      (224, 227, 228), BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:orange_concrete_powder",     (228, 143, 55),  BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:magenta_concrete_powder",    (196, 92, 190),  BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:light_blue_concrete_powder", (104, 165, 207), BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:yellow_concrete_powder",     (232, 200, 59),  BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:lime_concrete_powder",       (147, 205, 67),  BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:pink_concrete_powder",       (232, 170, 187), BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:gray_concrete_powder",       (76, 79, 84),    BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:light_gray_concrete_powder", (168, 168, 160), BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:cyan_concrete_powder",       (36, 153, 170),  BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:purple_concrete_powder",     (133, 64, 185),  BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:blue_concrete_powder",       (70, 72, 164),   BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:brown_concrete_powder",      (127, 85, 55),   BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:green_concrete_powder",      (100, 126, 52),  BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:red_concrete_powder",        (167, 54, 51),   BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),
    _u("minecraft:black_concrete_powder",      (26, 29, 36),    BlockConstraint.GRAVITY | BlockConstraint.PHASE_CHANGE),

    # ── Wool (16) — uniform, no constraints ────────────────────────────────
    _u("minecraft:white_wool",       (234, 236, 236)),
    _u("minecraft:orange_wool",      (241, 118, 20)),
    _u("minecraft:magenta_wool",     (189, 68, 179)),
    _u("minecraft:light_blue_wool",  (58, 175, 217)),
    _u("minecraft:yellow_wool",      (249, 198, 40)),
    _u("minecraft:lime_wool",        (112, 185, 26)),
    _u("minecraft:pink_wool",        (238, 141, 172)),
    _u("minecraft:gray_wool",        (63, 68, 72)),
    _u("minecraft:light_gray_wool",  (142, 142, 135)),
    _u("minecraft:cyan_wool",        (21, 138, 145)),
    _u("minecraft:purple_wool",      (121, 42, 173)),
    _u("minecraft:blue_wool",        (53, 57, 157)),
    _u("minecraft:brown_wool",       (114, 72, 41)),
    _u("minecraft:green_wool",       (85, 110, 28)),
    _u("minecraft:red_wool",         (162, 38, 35)),
    _u("minecraft:black_wool",       (20, 21, 26)),

    # ── Terracotta (17) — uniform ─────────────────────────────────────────
    _u("minecraft:terracotta",                 (152, 94, 68)),
    _u("minecraft:white_terracotta",           (210, 178, 161)),
    _u("minecraft:orange_terracotta",          (162, 84, 38)),
    _u("minecraft:magenta_terracotta",         (150, 88, 109)),
    _u("minecraft:light_blue_terracotta",      (113, 109, 138)),
    _u("minecraft:yellow_terracotta",          (186, 133, 36)),
    _u("minecraft:lime_terracotta",            (104, 118, 53)),
    _u("minecraft:pink_terracotta",            (162, 78, 79)),
    _u("minecraft:gray_terracotta",            (58, 42, 36)),
    _u("minecraft:light_gray_terracotta",      (135, 107, 98)),
    _u("minecraft:cyan_terracotta",            (87, 92, 92)),
    _u("minecraft:purple_terracotta",          (118, 70, 86)),
    _u("minecraft:blue_terracotta",            (74, 60, 91)),
    _u("minecraft:brown_terracotta",           (77, 51, 36)),
    _u("minecraft:green_terracotta",           (76, 83, 42)),
    _u("minecraft:red_terracotta",             (143, 61, 47)),
    _u("minecraft:black_terracotta",           (37, 23, 17)),

    # ── Stained Glass (16) — TRANSLUCENT ──────────────────────────────────
    _u("minecraft:white_stained_glass",      (255, 255, 255), BlockConstraint.TRANSLUCENT),
    _u("minecraft:orange_stained_glass",     (216, 127, 51),  BlockConstraint.TRANSLUCENT),
    _u("minecraft:magenta_stained_glass",    (178, 76, 216),  BlockConstraint.TRANSLUCENT),
    _u("minecraft:light_blue_stained_glass", (102, 153, 216), BlockConstraint.TRANSLUCENT),
    _u("minecraft:yellow_stained_glass",     (229, 229, 51),  BlockConstraint.TRANSLUCENT),
    _u("minecraft:lime_stained_glass",       (127, 204, 25),  BlockConstraint.TRANSLUCENT),
    _u("minecraft:pink_stained_glass",       (242, 127, 165), BlockConstraint.TRANSLUCENT),
    _u("minecraft:gray_stained_glass",       (76, 76, 76),    BlockConstraint.TRANSLUCENT),
    _u("minecraft:light_gray_stained_glass", (153, 153, 153), BlockConstraint.TRANSLUCENT),
    _u("minecraft:cyan_stained_glass",       (76, 127, 153),  BlockConstraint.TRANSLUCENT),
    _u("minecraft:purple_stained_glass",     (127, 63, 178),  BlockConstraint.TRANSLUCENT),
    _u("minecraft:blue_stained_glass",       (51, 76, 178),   BlockConstraint.TRANSLUCENT),
    _u("minecraft:brown_stained_glass",      (102, 76, 51),   BlockConstraint.TRANSLUCENT),
    _u("minecraft:green_stained_glass",      (102, 127, 51),  BlockConstraint.TRANSLUCENT),
    _u("minecraft:red_stained_glass",        (153, 51, 51),   BlockConstraint.TRANSLUCENT),
    _u("minecraft:black_stained_glass",      (25, 25, 25),    BlockConstraint.TRANSLUCENT),

    # ── Glazed Terracotta (16) — uniform avg ──────────────────────────────
    _u("minecraft:white_glazed_terracotta",      (188, 212, 202)),
    _u("minecraft:orange_glazed_terracotta",     (154, 147, 91)),
    _u("minecraft:magenta_glazed_terracotta",    (208, 100, 155)),
    _u("minecraft:light_blue_glazed_terracotta", (99, 168, 189)),
    _u("minecraft:yellow_glazed_terracotta",     (234, 192, 88)),
    _u("minecraft:lime_glazed_terracotta",       (162, 197, 55)),
    _u("minecraft:pink_glazed_terracotta",       (235, 154, 181)),
    _u("minecraft:gray_glazed_terracotta",       (83, 100, 100)),
    _u("minecraft:light_gray_glazed_terracotta", (144, 166, 167)),
    _u("minecraft:cyan_glazed_terracotta",       (52, 118, 119)),
    _u("minecraft:purple_glazed_terracotta",     (109, 48, 118)),
    _u("minecraft:blue_glazed_terracotta",       (47, 65, 139)),
    _u("minecraft:brown_glazed_terracotta",      (119, 106, 85)),
    _u("minecraft:green_glazed_terracotta",      (117, 142, 67)),
    _u("minecraft:red_glazed_terracotta",        (181, 59, 53)),
    _u("minecraft:black_glazed_terracotta",      (67, 30, 32)),

    # ── Stone Variants ────────────────────────────────────────────────────
    _u("minecraft:stone",                        (125, 125, 125)),
    _u("minecraft:cobblestone",                  (127, 127, 127)),
    _u("minecraft:stone_bricks",                 (122, 122, 122)),
    _u("minecraft:mossy_stone_bricks",           (115, 121, 105)),
    _u("minecraft:cracked_stone_bricks",         (118, 117, 118)),
    _u("minecraft:chiseled_stone_bricks",        (116, 116, 116)),
    _u("minecraft:smooth_stone",                 (158, 158, 158)),
    _u("minecraft:granite",                      (149, 103, 86)),
    _u("minecraft:polished_granite",             (154, 107, 89)),
    _u("minecraft:diorite",                      (189, 188, 189)),
    _u("minecraft:polished_diorite",             (192, 193, 194)),
    _u("minecraft:andesite",                     (136, 136, 137)),
    _u("minecraft:polished_andesite",            (132, 135, 133)),
    _u("minecraft:deepslate",                    (100, 100, 100)),
    _u("minecraft:cobbled_deepslate",            (77, 77, 80)),
    _u("minecraft:polished_deepslate",           (72, 72, 73)),
    _u("minecraft:deepslate_bricks",             (70, 70, 71)),
    _u("minecraft:cracked_deepslate_bricks",     (68, 68, 69)),
    _u("minecraft:deepslate_tiles",              (54, 54, 55)),
    _u("minecraft:cracked_deepslate_tiles",      (52, 52, 53)),
    _u("minecraft:chiseled_deepslate",           (64, 64, 66)),
    _u("minecraft:reinforced_deepslate",         (86, 90, 82)),
    _u("minecraft:tuff",                         (108, 109, 102)),
    _u("minecraft:tuff_bricks",                  (105, 106, 100)),
    _u("minecraft:polished_tuff",                (106, 108, 100)),
    _u("minecraft:chiseled_tuff",                (110, 110, 104)),
    _u("minecraft:calcite",                      (224, 224, 220)),
    _u("minecraft:dripstone_block",              (134, 107, 92)),
    _u("minecraft:sandstone",                    (217, 206, 159)),
    _u("minecraft:smooth_sandstone",             (217, 207, 159)),
    _u("minecraft:chiseled_sandstone",           (214, 203, 156)),
    _u("minecraft:cut_sandstone",                (215, 204, 157)),
    _u("minecraft:red_sandstone",                (186, 99, 29)),
    _u("minecraft:smooth_red_sandstone",         (187, 100, 30)),
    _u("minecraft:chiseled_red_sandstone",       (184, 98, 29)),
    _u("minecraft:cut_red_sandstone",            (185, 99, 29)),
    _u("minecraft:prismarine",                   (99, 171, 158)),
    _u("minecraft:prismarine_bricks",            (99, 171, 158)),
    _u("minecraft:dark_prismarine",              (51, 91, 75)),
    _u("minecraft:blackstone",                   (42, 36, 40)),
    _u("minecraft:polished_blackstone",          (53, 49, 51)),
    _u("minecraft:polished_blackstone_bricks",   (48, 43, 46)),
    _u("minecraft:chiseled_polished_blackstone", (50, 45, 48)),
    _u("minecraft:gilded_blackstone",            (64, 50, 35)),
    _u("minecraft:basalt",                       (73, 72, 77)),
    _u("minecraft:smooth_basalt",                (72, 72, 74)),
    _u("minecraft:polished_basalt",              (75, 74, 79)),
    _u("minecraft:obsidian",                     (15, 11, 25)),
    _u("minecraft:crying_obsidian",              (32, 10, 61)),
    _u("minecraft:end_stone",                    (219, 223, 158)),
    _u("minecraft:end_stone_bricks",             (218, 224, 162)),
    _u("minecraft:purpur_block",                 (170, 126, 170)),
    _u("minecraft:purpur_pillar",                (168, 125, 168)),
    _u("minecraft:nether_bricks",                (44, 21, 26)),
    _u("minecraft:cracked_nether_bricks",        (42, 20, 24)),
    _u("minecraft:chiseled_nether_bricks",       (44, 22, 26)),
    _u("minecraft:red_nether_bricks",            (69, 7, 9)),
    _u("minecraft:quartz_block",                 (236, 230, 223)),
    _u("minecraft:smooth_quartz",                (236, 230, 223)),
    _u("minecraft:chiseled_quartz_block",        (233, 227, 219)),
    _u("minecraft:quartz_pillar",                (235, 229, 221)),
    _u("minecraft:quartz_bricks",                (234, 229, 222)),
    _u("minecraft:bricks",                       (150, 97, 83)),
    _u("minecraft:mud_bricks",                   (137, 104, 79)),
    _u("minecraft:packed_mud",                   (142, 107, 80)),

    # ── Wood Planks (11) — uniform, GROWTH-safe ───────────────────────────
    _u("minecraft:oak_planks",       (162, 131, 79)),
    _u("minecraft:spruce_planks",    (115, 85, 49)),
    _u("minecraft:birch_planks",     (196, 179, 123)),
    _u("minecraft:jungle_planks",    (160, 115, 81)),
    _u("minecraft:acacia_planks",    (169, 92, 52)),
    _u("minecraft:dark_oak_planks",  (67, 43, 20)),
    _u("minecraft:crimson_planks",   (101, 48, 69)),
    _u("minecraft:warped_planks",    (43, 105, 99)),
    _u("minecraft:mangrove_planks",  (118, 54, 49)),
    _u("minecraft:cherry_planks",    (227, 178, 163)),
    _u("minecraft:bamboo_planks",    (195, 176, 85)),
    _u("minecraft:bamboo_mosaic",    (191, 170, 80)),

    # ── All-Bark Wood Blocks (11) — uniform (bark on all sides) ───────────
    # Using `_wood` species variants where bark wraps all 6 faces.
    # For bamboo there's no "bamboo_wood" — skip.
]

# Programmatically emit log entries.
# oak_log[axis=y]: top/bottom = rings, sides = bark
# oak_log[axis=x]: top/bottom = bark (rotated), sides = rings on ±z, bark on ±y
# For Phase 1 we model axis=y and axis=x to cover rings-side vs bark-side cases.
# bamboo_block has a single axis state visually; use default (axis=y).
for _species, (_bark, _rings) in _WOODS.items():
    # Stem naming: nether fungus -> _stem, bamboo -> _block, others -> _log
    if _species in ("crimson", "warped"):
        stem = "stem"
    elif _species == "bamboo":
        stem = "block"
    else:
        stem = "log"
    # axis=y: top=rings, side=bark, bottom=rings
    _ENTRIES.append(_a(f"minecraft:{_species}_{stem}[axis=y]", _rings, _bark, _rings))
    # axis=x: top=bark, side=rings (visible on ±z for wall mural, on ±y for ground mural)
    _ENTRIES.append(_a(f"minecraft:{_species}_{stem}[axis=x]", _bark, _rings, _bark))
    # All-bark "wood" block (no stripped version for nether fungus — use hyphae)
    wood_suffix = "hyphae" if _species in ("crimson", "warped") else "wood"
    if _species != "bamboo":  # bamboo has no _wood variant
        _ENTRIES.append(_u(f"minecraft:{_species}_{wood_suffix}[axis=y]", _bark))

# Stripped logs
for _species, (_bark_s, _rings_s) in _STRIPPED.items():
    stem = "stem" if _species in ("crimson", "warped") else "log"
    _ENTRIES.append(_a(f"minecraft:stripped_{_species}_{stem}[axis=y]", _rings_s, _bark_s, _rings_s))
    _ENTRIES.append(_a(f"minecraft:stripped_{_species}_{stem}[axis=x]", _bark_s, _rings_s, _bark_s))
    wood_suffix = "hyphae" if _species in ("crimson", "warped") else "wood"
    _ENTRIES.append(_u(f"minecraft:stripped_{_species}_{wood_suffix}[axis=y]", _bark_s))

# bamboo stripped is a separate branch (no rings/bark asymmetry — uniform color)
_ENTRIES.append(_a("minecraft:stripped_bamboo_block[axis=y]", (219, 198, 117), (220, 202, 126), (219, 198, 117)))
_ENTRIES.append(_a("minecraft:stripped_bamboo_block[axis=x]", (220, 202, 126), (219, 198, 117), (220, 202, 126)))

_ENTRIES.extend([
    # ── Natural / Misc ────────────────────────────────────────────────────
    _u("minecraft:dirt",                  (134, 96, 67)),
    _u("minecraft:coarse_dirt",           (120, 84, 58)),
    _u("minecraft:rooted_dirt",           (146, 108, 80)),
    _u("minecraft:podzol",                (92, 67, 38)),
    _u("minecraft:grass_block",           (127, 178, 56), BlockConstraint.BIOME_TINTED),
    _u("minecraft:dirt_path",             (148, 124, 70)),
    _u("minecraft:farmland",              (137, 99, 65), BlockConstraint.WALK_UNSAFE),
    _u("minecraft:sand",                  (219, 207, 163), BlockConstraint.GRAVITY),
    _u("minecraft:red_sand",              (190, 102, 33),  BlockConstraint.GRAVITY),
    _u("minecraft:gravel",                (131, 127, 126), BlockConstraint.GRAVITY),
    _u("minecraft:clay",                  (161, 166, 179)),
    _u("minecraft:mud",                   (60, 57, 61), BlockConstraint.WALK_UNSAFE),
    _u("minecraft:moss_block",            (89, 109, 45)),
    _u("minecraft:pale_moss_block",       (118, 125, 110)),
    _u("minecraft:snow_block",            (249, 254, 254)),
    _u("minecraft:powder_snow",           (245, 250, 250), BlockConstraint.WALK_UNSAFE),
    _u("minecraft:ice",                   (145, 190, 230), BlockConstraint.TRANSLUCENT),
    _u("minecraft:packed_ice",            (141, 180, 224), BlockConstraint.TRANSLUCENT),
    _u("minecraft:blue_ice",              (116, 167, 253), BlockConstraint.TRANSLUCENT),
    _u("minecraft:netherrack",            (97, 38, 38)),
    _u("minecraft:nether_wart_block",     (119, 7, 7)),
    _u("minecraft:warped_wart_block",     (22, 117, 109)),
    _u("minecraft:soul_sand",             (81, 62, 51), BlockConstraint.GRAVITY | BlockConstraint.WALK_UNSAFE),
    _u("minecraft:soul_soil",             (75, 57, 47)),
    _u("minecraft:magma_block",           (142, 63, 31), BlockConstraint.WALK_UNSAFE),
    _u("minecraft:glowstone",             (171, 131, 84)),
    _u("minecraft:sea_lantern",           (172, 199, 190)),
    _u("minecraft:shroomlight",           (240, 147, 55)),
    _u("minecraft:amethyst_block",        (133, 97, 168)),
    _u("minecraft:budding_amethyst",      (131, 95, 166)),
    _u("minecraft:honey_block",           (251, 186, 52), BlockConstraint.TRANSLUCENT),
    _u("minecraft:honeycomb_block",       (229, 148, 29)),
    _u("minecraft:slime_block",           (112, 196, 86), BlockConstraint.TRANSLUCENT),
    _u("minecraft:sponge",                (196, 192, 74)),
    _u("minecraft:wet_sponge",            (170, 181, 70)),
    _u("minecraft:bone_block[axis=y]",    (229, 225, 207)),

    # ── Ore / Metal Blocks ────────────────────────────────────────────────
    _u("minecraft:iron_block",       (220, 220, 220)),
    _u("minecraft:raw_iron_block",   (169, 133, 96)),
    _u("minecraft:gold_block",       (246, 208, 62)),
    _u("minecraft:raw_gold_block",   (218, 168, 55)),
    _u("minecraft:diamond_block",    (98, 237, 228)),
    _u("minecraft:emerald_block",    (81, 217, 117)),
    _u("minecraft:lapis_block",      (31, 67, 140)),
    _u("minecraft:redstone_block",   (175, 24, 5)),
    _u("minecraft:coal_block",       (16, 16, 16)),
    _u("minecraft:netherite_block",  (66, 61, 63)),

    # ── Copper Variants — TRANSITION states fixed with waxed_ ──────────────
    # Unwaxed copper oxidizes over time; use waxed_ for pixel-stable color.
    _u("minecraft:waxed_copper_block",             (192, 107, 79)),
    _u("minecraft:waxed_exposed_copper",           (162, 119, 94)),
    _u("minecraft:waxed_weathered_copper",         (109, 145, 107)),
    _u("minecraft:waxed_oxidized_copper",          (82, 162, 132)),
    _u("minecraft:waxed_cut_copper",               (192, 107, 79)),
    _u("minecraft:waxed_exposed_cut_copper",       (162, 119, 94)),
    _u("minecraft:waxed_weathered_cut_copper",     (109, 145, 107)),
    _u("minecraft:waxed_oxidized_cut_copper",      (82, 162, 132)),
    _u("minecraft:waxed_chiseled_copper",          (188, 104, 77)),
    _u("minecraft:waxed_exposed_chiseled_copper",  (158, 116, 92)),
    _u("minecraft:waxed_weathered_chiseled_copper", (106, 142, 104)),
    _u("minecraft:waxed_oxidized_chiseled_copper", (80, 160, 130)),

    # ── Glass / Translucent ───────────────────────────────────────────────
    _u("minecraft:glass",          (200, 228, 235), BlockConstraint.TRANSLUCENT),
    _u("minecraft:tinted_glass",   (44, 38, 50),    BlockConstraint.TRANSLUCENT),

    # ── Light Sources (for backlight) ─────────────────────────────────────
    # light block: invisible in survival but placed by WorldEdit; level controls brightness
    _u("minecraft:light[level=15]", (255, 255, 128), BlockConstraint.TRANSLUCENT),

    # ── Utility / Decorative ──────────────────────────────────────────────
    _u("minecraft:bookshelf",              (108, 88, 58)),
    _u("minecraft:chiseled_bookshelf",     (108, 88, 58)),
    _u("minecraft:hay_block[axis=y]",      (166, 139, 37)),
    _u("minecraft:melon",                  (111, 145, 30)),
    _u("minecraft:pumpkin",                (198, 119, 8)),
    _u("minecraft:carved_pumpkin",         (198, 119, 8)),
    _u("minecraft:jack_o_lantern",         (198, 119, 8)),
    _u("minecraft:dried_kelp_block",       (55, 67, 39)),
    _u("minecraft:target",                 (221, 176, 163)),
    _u("minecraft:ochre_froglight",        (253, 242, 209)),
    _u("minecraft:verdant_froglight",      (216, 240, 192)),
    _u("minecraft:pearlescent_froglight",  (246, 221, 237)),
    _u("minecraft:sculk",                  (14, 21, 27)),
    _u("minecraft:sculk_catalyst",         (16, 23, 30)),
    _u("minecraft:resin_block",            (215, 119, 39)),
    _u("minecraft:resin_bricks",           (208, 108, 33)),
])

# ── Back-compat view (legacy tests / fidelity.py) ──────────────────────────
# BLOCK_COLORS: dict[block_id, side_rgb]. Keys strip block state for legacy use
# so `oak_log` still maps (falling through to axis=y entry).
_PALETTE_BY_ID: dict[str, BlockEntry] = {e.block_id: e for e in _ENTRIES}

# Strip-state aliases: "oak_log" → entry of "oak_log[axis=y]" if present
_STATE_STRIPPED_ALIASES: dict[str, BlockEntry] = {}
for _entry in _ENTRIES:
    clean = _entry.block_id.split("[")[0]
    # Prefer axis=y as the canonical form; don't overwrite if an axis=y already set
    existing = _STATE_STRIPPED_ALIASES.get(clean)
    if existing is None:
        _STATE_STRIPPED_ALIASES[clean] = _entry
    elif "[axis=y]" in _entry.block_id:
        _STATE_STRIPPED_ALIASES[clean] = _entry

BLOCK_COLORS: dict[str, tuple[int, int, int]] = {
    **{clean: e.side_rgb for clean, e in _STATE_STRIPPED_ALIASES.items()},
    **{e.block_id: e.side_rgb for e in _ENTRIES},
}


def get_color(block_id: str) -> tuple[int, int, int]:
    """Get RGB side-face color for a block ID (backward-compatible).

    Exact match wins; else strips block state and retries; else FALLBACK_COLOR.
    """
    entry = _PALETTE_BY_ID.get(block_id)
    if entry is not None:
        return entry.side_rgb
    clean = block_id.split("[")[0]
    entry = _STATE_STRIPPED_ALIASES.get(clean)
    if entry is not None:
        return entry.side_rgb
    return FALLBACK_COLOR


def get_entry(block_id: str) -> BlockEntry | None:
    """Exact-match BlockEntry lookup (no state-stripping)."""
    return _PALETTE_BY_ID.get(block_id)


def list_palette(
    face: str = "side",
    include: BlockConstraint = BlockConstraint.NONE,
) -> list[BlockEntry]:
    """Return palette entries whose constraints are a subset of `include`.

    `include` is an allow-set: an entry passes iff `(entry.constraints & ~include) == NONE`.
    The default (`include=NONE`) returns only NONE-constraint entries.

    `face` is a hint for the caller (PaletteIndex) about which face to sample; this
    function does not filter by face, it only returns entries.
    """
    _ = face  # consumed by caller via effective_rgb()
    allowed_mask = include
    result: list[BlockEntry] = []
    for e in _ENTRIES:
        # entry is allowed if every one of its constraint bits is set in include
        if (e.constraints & ~allowed_mask) == BlockConstraint.NONE:
            result.append(e)
    return result


def all_entries() -> list[BlockEntry]:
    """Return all entries unfiltered (for validation scripts)."""
    return list(_ENTRIES)
