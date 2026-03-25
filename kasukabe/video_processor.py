"""Extract key frames from video using ffmpeg."""
from __future__ import annotations
import glob
import json
import shutil
import subprocess
from pathlib import Path


class VideoProcessingError(Exception):
    pass


def _check_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise VideoProcessingError("ffmpeg not found in PATH. Install with: brew install ffmpeg")
    if not shutil.which("ffprobe"):
        raise VideoProcessingError("ffprobe not found in PATH. Install ffmpeg package.")


def get_video_duration(video_path: str) -> float:
    """Return video duration in seconds using ffprobe."""
    _check_ffmpeg()
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise VideoProcessingError(f"ffprobe failed: {result.stderr}")
    data = json.loads(result.stdout)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            duration = stream.get("duration")
            if duration:
                return float(duration)
    raise VideoProcessingError("Could not determine video duration")


def extract_keyframes(
    video_path: str,
    output_dir: Path,
    max_frames: int = 8,
    scene_threshold: float = 0.3,
) -> list[Path]:
    """Extract up to max_frames key frames from video.

    Strategy: scene-change detection first; falls back to time-based if < 3 scenes.

    Args:
        video_path: Path to input video file.
        output_dir: Directory to write extracted frames (will be created).
        max_frames: Maximum number of frames to extract (default 8).
        scene_threshold: Scene change sensitivity 0.0–1.0 (default 0.3).

    Returns:
        Sorted list of extracted frame paths (JPEG).

    Raises:
        VideoProcessingError: If ffmpeg is missing or video is unreadable.
    """
    _check_ffmpeg()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean any existing frames
    for f in output_dir.glob("frame_*.jpg"):
        f.unlink()

    pattern = str(output_dir / "frame_%03d.jpg")

    # --- Attempt 1: scene-change detection ---
    scene_result = subprocess.run(
        [
            "ffmpeg", "-i", str(video_path),
            "-vf", f"select=gt(scene\\,{scene_threshold}),scale=1280:720",
            "-vsync", "vfr",
            "-frames:v", str(max_frames),
            "-q:v", "4",  # JPEG quality ~80%
            pattern,
            "-y",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    # Non-zero returncode is expected when no scene changes were detected;
    # we fall through to time-based sampling in that case.

    frames = sorted(output_dir.glob("frame_*.jpg"))

    if len(frames) >= 3:
        return frames[:max_frames]

    # --- Fallback: time-based uniform sampling ---
    for f in frames:
        f.unlink()

    try:
        duration = get_video_duration(str(video_path))
        interval = max(1, int(duration / max_frames))
    except VideoProcessingError:
        interval = 5  # default 1 frame per 5 seconds

    time_result = subprocess.run(
        [
            "ffmpeg", "-i", str(video_path),
            "-vf", f"fps=1/{interval},scale=1280:720",
            "-frames:v", str(max_frames),
            "-q:v", "4",
            pattern,
            "-y",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if time_result.returncode != 0:
        raise VideoProcessingError(f"ffmpeg failed: {time_result.stderr[-500:]}")

    frames = sorted(output_dir.glob("frame_*.jpg"))
    if not frames:
        raise VideoProcessingError("ffmpeg produced no frames — check video file")

    return frames[:max_frames]


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        prog="kasukabe.video_processor",
        description="Extract keyframes from video for Minecraft building analysis.",
    )
    parser.add_argument("--input", "-i", required=True, help="Path to video file")
    parser.add_argument("--output-dir", "-o", required=True, help="Output directory for frames")
    parser.add_argument("--max-frames", type=int, default=8, help="Maximum frames to extract")

    args = parser.parse_args()
    frames = extract_keyframes(args.input, Path(args.output_dir), max_frames=args.max_frames)
    for f in frames:
        print(f)
    print(f"Extracted {len(frames)} frames.")


if __name__ == "__main__":
    main()
