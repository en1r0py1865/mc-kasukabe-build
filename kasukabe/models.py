"""Shared data models for kasukabe building studio."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class BlockOp:
    """A single block placement operation."""
    x: int
    y: int
    z: int
    block: str  # e.g. "minecraft:oak_planks"
