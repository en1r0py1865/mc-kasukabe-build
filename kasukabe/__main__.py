"""CLI entry point for kasukabe Minecraft AI Building Studio."""
from __future__ import annotations

import sys
from pathlib import Path


def _parse_origin(value: str) -> tuple[int, int, int]:
    parts = value.split(",")
    if len(parts) != 3:
        raise ValueError(f"origin must be x,y,z (e.g. 100,64,200), got: {value!r}")
    return tuple(int(p.strip()) for p in parts)  # type: ignore[return-value]


def _parse_size(value: str) -> tuple[int, int, int]:
    parts = value.lower().replace("x", ",").split(",")
    if len(parts) != 3:
        raise ValueError(f"size must be WxHxL (e.g. 12x8x10), got: {value!r}")
    return tuple(int(p.strip()) for p in parts)  # type: ignore[return-value]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="kasukabe",
        description="Minecraft AI Building Studio — build structures from images or video.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  kasukabe build --input house.jpg --origin 100,64,200 --size 12x8x10
  kasukabe build --input timelapse.mp4 --origin 100,64,200
  kasukabe build --input cabin.png   # size auto-detected from vision
        """,
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    build_parser = sub.add_parser("build", help="Build a structure from an image or video")
    build_parser.add_argument(
        "--input", "-i", required=True,
        help="Path to input image (jpg/png) or video (mp4/mov/etc.)",
    )
    build_parser.add_argument(
        "--origin", "-o", default="100,64,200",
        help="World coordinates of build origin: x,y,z (default: 100,64,200)",
    )
    build_parser.add_argument(
        "--size", "-s", default=None,
        help="Override build size: WxHxL in blocks (default: auto-detect from vision)",
    )
    build_parser.add_argument(
        "--workspace", "-w", default="workspace",
        help="Workspace directory for session files (default: workspace/)",
    )

    args = parser.parse_args()

    if args.command == "build":
        _cmd_build(args)
    else:
        parser.print_help()
        sys.exit(1)


def _cmd_build(args: object) -> None:
    from kasukabe.foreman import Foreman

    input_path = getattr(args, "input")
    if not Path(input_path).exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        origin = _parse_origin(getattr(args, "origin"))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    size: tuple[int, int, int] = (0, 0, 0)
    raw_size = getattr(args, "size")
    if raw_size:
        try:
            size = _parse_size(raw_size)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    workspace = getattr(args, "workspace", "workspace")

    foreman = Foreman(workspace_root=workspace)
    try:
        session = foreman.run(input_path=input_path, origin=origin, size=size)
    except Exception as exc:  # noqa: BLE001
        print(f"\nBuild failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"Build complete!")
    print(f"  Session:         {session.session_id}")
    print(f"  Completion rate: {session.completion_rate:.1%}")
    print(f"  Iterations:      {session.iteration}")
    print(f"  Workspace:       {workspace}/{session.session_id}/")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
