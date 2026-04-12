#!/usr/bin/env python3
"""Generate chunked Minecraft fill commands that respect the 32768 block limit."""
from __future__ import annotations

import argparse
import sys


def generate_fills(
    x1: int, y1: int, z1: int,
    x2: int, y2: int, z2: int,
    block: str,
    limit: int = 32768,
) -> list[str]:
    """Split a fill region into per-layer commands, each under ``limit`` blocks.

    Strategy: iterate by y-layer. If a single layer exceeds the limit,
    subdivide along the x-axis.
    """
    commands: list[str] = []
    dx = x2 - x1 + 1
    dz = z2 - z1 + 1

    for y in range(y1, y2 + 1):
        area = dx * dz
        if area <= limit:
            commands.append(f"fill {x1} {y} {z1} {x2} {y} {z2} {block}")
        else:
            num_splits = (area + limit - 1) // limit
            step_x = (dx + num_splits - 1) // num_splits
            for x in range(x1, x2 + 1, step_x):
                xe = min(x + step_x - 1, x2)
                commands.append(f"fill {x} {y} {z1} {xe} {y} {z2} {block}")
    return commands


def _parse_region(value: str) -> tuple[int, int, int, int, int, int]:
    parts = value.split(",")
    if len(parts) != 6:
        raise argparse.ArgumentTypeError(
            f"region must be x1,y1,z1,x2,y2,z2 — got: {value!r}"
        )
    return tuple(int(p.strip()) for p in parts)  # type: ignore[return-value]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gen_fills",
        description="Generate chunked Minecraft fill commands.",
    )
    parser.add_argument(
        "--region", required=True, type=_parse_region,
        help="Fill region as x1,y1,z1,x2,y2,z2",
    )
    parser.add_argument(
        "--block", required=True,
        help="Block ID (e.g. minecraft:stone)",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output file (default: stdout)",
    )
    parser.add_argument(
        "--limit", type=int, default=32768,
        help="Max blocks per fill command (default: 32768)",
    )

    args = parser.parse_args()
    x1, y1, z1, x2, y2, z2 = args.region
    commands = generate_fills(x1, y1, z1, x2, y2, z2, args.block, args.limit)

    output = "\n".join(commands) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Wrote {len(commands)} commands to {args.output}")
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
