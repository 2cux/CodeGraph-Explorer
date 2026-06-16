"""Tests for CheckpointManager — PRD Section 26.4.5.

Covers:
- record_checkpoint (single, multiple)
- list_checkpoints (ordering, parsing)
- get_checkpoint (by name, not found)
- JSONL format correctness
- Empty file handling
- Corrupted line handling (resilience)
- Edge cases (empty payload, unicode)
"""

from __future__ import annotations

import json
from pathlib import Path

from codegraph.harness.checkpoints import CheckpointManager
from codegraph.harness.models import HarnessCheckpoint


# ── record_checkpoint ──────────────────────────────────────────────────────


class TestRecordCheckpoint:
    def test_record_single_checkpoint(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        cp = cpm.record_checkpoint("symbols resolved", {"count": 42})

        assert cp.name == "symbols resolved"
        assert cp.status == "recorded"
        assert cp.payload == {"count": 42}
        assert cp.created_at  # should be an ISO timestamp
        assert "T" in cp.created_at

    def test_record_checkpoint_creates_file(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        cpm.record_checkpoint("step-1")
        assert cpm.path.exists()

    def test_record_checkpoint_appends_jsonl(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        cpm.record_checkpoint("first")
        cpm.record_checkpoint("second", {"step": 2})

        lines = cpm.path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        data1 = json.loads(lines[0])
        data2 = json.loads(lines[1])
        assert data1["name"] == "first"
        assert data2["name"] == "second"
        assert data2["payload"]["step"] == 2

    def test_record_checkpoint_with_none_payload(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        cp = cpm.record_checkpoint("no payload", None)
        assert cp.payload == {}

    def test_record_checkpoint_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Should create parent directories if they don't exist."""
        deep_dir = tmp_path / "deep" / "nested" / "path"
        cpm = CheckpointManager(deep_dir)
        cp = cpm.record_checkpoint("deep checkpoint")
        assert deep_dir.exists()
        assert cp.name == "deep checkpoint"

    def test_record_checkpoint_unicode_payload(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        cp = cpm.record_checkpoint("unicode", {"message": "你好世界", "emoji": "🚀"})
        assert cp.payload["message"] == "你好世界"
        assert cp.payload["emoji"] == "🚀"

        # Verify file content is valid JSON with unicode
        lines = cpm.path.read_text(encoding="utf-8").strip().splitlines()
        data = json.loads(lines[0])
        assert data["payload"]["message"] == "你好世界"


# ── list_checkpoints ───────────────────────────────────────────────────────


class TestListCheckpoints:
    def test_list_empty_returns_empty_list(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        assert cpm.list_checkpoints() == []

    def test_list_returns_in_record_order(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        cpm.record_checkpoint("step-1")
        cpm.record_checkpoint("step-2")
        cpm.record_checkpoint("step-3")

        checkpoints = cpm.list_checkpoints()
        assert len(checkpoints) == 3
        assert [cp.name for cp in checkpoints] == ["step-1", "step-2", "step-3"]

    def test_list_returns_harness_checkpoint_objects(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        cpm.record_checkpoint("test", {"value": 99})

        checkpoints = cpm.list_checkpoints()
        assert len(checkpoints) == 1
        assert isinstance(checkpoints[0], HarnessCheckpoint)
        assert checkpoints[0].name == "test"
        assert checkpoints[0].payload["value"] == 99

    def test_list_with_corrupted_line_skips_it(self, tmp_path: Path) -> None:
        """Corrupted JSONL lines should be silently skipped."""
        cpm = CheckpointManager(tmp_path)
        cpm.record_checkpoint("good-1")
        # Append a corrupted line directly
        with open(cpm.path, "a", encoding="utf-8") as f:
            f.write("not valid json\n")
        cpm.record_checkpoint("good-2")

        checkpoints = cpm.list_checkpoints()
        assert len(checkpoints) == 2
        assert checkpoints[0].name == "good-1"
        assert checkpoints[1].name == "good-2"

    def test_list_with_empty_lines_skips_them(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        cpm.record_checkpoint("good")
        # Append empty lines
        with open(cpm.path, "a", encoding="utf-8") as f:
            f.write("\n\n")
        checkpoints = cpm.list_checkpoints()
        assert len(checkpoints) == 1

    def test_list_file_does_not_exist_returns_empty(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        # Never record anything
        assert cpm.list_checkpoints() == []


# ── get_checkpoint ─────────────────────────────────────────────────────────


class TestGetCheckpoint:
    def test_get_by_name_returns_first_match(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        cpm.record_checkpoint("inputs.normalized", {"count": 1})
        cpm.record_checkpoint("inputs.normalized", {"count": 2})  # duplicate name

        cp = cpm.get_checkpoint("inputs.normalized")
        assert cp is not None
        assert cp.payload["count"] == 1  # first match

    def test_get_by_name_not_found_returns_none(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        cpm.record_checkpoint("existing")
        assert cpm.get_checkpoint("nonexistent") is None

    def test_get_from_empty_file_returns_none(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        assert cpm.get_checkpoint("anything") is None


# ── Path property ──────────────────────────────────────────────────────────


class TestCheckpointPath:
    def test_path_property(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        assert cpm.path == tmp_path / "checkpoints.jsonl"


# ── Integration with realistic workflow data ───────────────────────────────


class TestCheckpointIntegration:
    def test_workflow_lifecycle_checkpoints(self, tmp_path: Path) -> None:
        cpm = CheckpointManager(tmp_path)
        cpm.record_checkpoint(
            "inputs.normalized",
            {"files": ["src/a.py"], "symbols": ["login"], "project_root": "/tmp"},
        )
        cpm.record_checkpoint(
            "workflow.impact.completed",
            {
                "risk_level": "medium",
                "planned_symbols": 2,
                "affected_files": 5,
                "affected_tests": 3,
            },
        )

        checkpoints = cpm.list_checkpoints()
        assert len(checkpoints) == 2
        assert checkpoints[0].name == "inputs.normalized"
        assert checkpoints[0].payload["files"] == ["src/a.py"]
        assert checkpoints[1].name == "workflow.impact.completed"
        assert checkpoints[1].payload["risk_level"] == "medium"
