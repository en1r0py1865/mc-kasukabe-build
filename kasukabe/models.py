"""Shared data models for kasukabe building studio."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BlockOp:
    """A single block placement operation."""
    x: int
    y: int
    z: int
    block: str  # e.g. "minecraft:oak_planks"


@dataclass
class SessionState:
    """Tracks the state of a single building session."""
    session_id: str
    input_path: str
    origin: tuple[int, int, int]
    size: tuple[int, int, int]  # (W, H, L); (0,0,0) means auto-detect from vision
    iteration: int = 0
    phase: str = "INIT"  # INIT|VIDEO_PROCESS|ARCHITECT|PLANNER|BUILDER|INSPECTOR|DONE|FAILED
    completion_rate: float = 0.0
    workspace_dir: Path = field(default_factory=lambda: Path("workspace"))
    failure_reason: str = ""


class PipelineBlocked(Exception):
    """Raised when an agent cannot proceed and the pipeline should halt."""
    pass
