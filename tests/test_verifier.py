# tests/test_verifier.py
"""Tests for block verification module."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kasukabe.verifier import verify, _stratified_sample, _blueprint_to_absolute


class TestBlueprintToAbsolute:
    def test_converts_relative_to_absolute(self):
        blueprint = {
            "blocks": [
                {"x": 0, "y": 0, "z": 0, "block": "minecraft:stone"},
                {"x": 1, "y": 2, "z": 3, "block": "minecraft:oak_planks"},
            ]
        }
        result = _blueprint_to_absolute(blueprint, (100, 64, 200))
        assert result[0] == {"x": 100, "y": 64, "z": 200, "block": "minecraft:stone"}
        assert result[1] == {"x": 101, "y": 66, "z": 203, "block": "minecraft:oak_planks"}

    def test_empty_blocks(self):
        assert _blueprint_to_absolute({"blocks": []}, (0, 0, 0)) == []


class TestStratifiedSample:
    def test_returns_all_if_under_max(self):
        blocks = [{"x": 0, "y": i, "z": 0, "block": "minecraft:stone"} for i in range(5)]
        result = _stratified_sample(blocks, 200)
        assert len(result) == 5

    def test_caps_at_max(self):
        blocks = [{"x": i, "y": i % 3, "z": 0, "block": "minecraft:stone"} for i in range(500)]
        result = _stratified_sample(blocks, 200)
        assert len(result) <= 200

    def test_samples_across_layers(self):
        blocks = []
        for y in range(10):
            for i in range(50):
                blocks.append({"x": i, "y": y, "z": 0, "block": "minecraft:stone"})
        result = _stratified_sample(blocks, 50)
        y_values = {b["y"] for b in result}
        assert len(y_values) >= 5  # should sample from multiple layers


class TestVerify:
    def test_writes_verification_result(self, tmp_path):
        blueprint = {
            "meta": {"origin": {"x": 100, "y": 64, "z": 200}},
            "blocks": [
                {"x": 0, "y": 0, "z": 0, "block": "minecraft:stone"},
                {"x": 1, "y": 0, "z": 0, "block": "minecraft:oak_planks"},
            ],
        }
        (tmp_path / "blueprint.json").write_text(json.dumps(blueprint))

        # Mock bridge to return matching blocks
        with patch("kasukabe.verifier.requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "blocks": [
                    {"x": 100, "y": 64, "z": 200, "block": "minecraft:stone", "found": True},
                    {"x": 101, "y": 64, "z": 200, "block": "minecraft:oak_planks", "found": True},
                ]
            }
            mock_resp.raise_for_status = MagicMock()
            mock_req.post.return_value = mock_resp

            result = verify(
                workspace_dir=tmp_path,
                origin=(100, 64, 200),
            )

        assert result["completion_rate"] == 1.0
        assert result["correct_blocks"] == 2
        assert (tmp_path / "verification_result.json").exists()

    def test_missing_blueprint_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            verify(workspace_dir=tmp_path, origin=(0, 0, 0))
