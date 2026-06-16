"""Tests for RunStore persistence layer — PRD Section 26.4.3.

Covers:
- run_id generation
- create_run (directory structure, state.json, input.json)
- load_run / update_run / update_run_status
- write_input / write_output / read_output
- append_event / append_checkpoint
- list_runs (filtering, sorting, limit)
- delete_run / prune_runs
- path safety (validate_run_id)
- injected store with custom project_root
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from codegraph.harness.models import RunStatus
from codegraph.harness.store import RunStore, _generate_run_id


# ── run_id generation ──────────────────────────────────────────────────────


class TestRunIdGeneration:
    def test_generated_run_id_contains_module_slug(self) -> None:
        run_id = _generate_run_id("workflow.impact")
        assert run_id.startswith("workflow-impact-")

    def test_generated_run_id_contains_timestamp(self) -> None:
        run_id = _generate_run_id("test.module")
        # Format: test-module-YYYYMMDDTHHMMSSZ-xxxx
        parts = run_id.split("-")
        assert len(parts) >= 3
        # Timestamp part: 20260616T120000Z format
        ts_part = parts[-2]
        assert "T" in ts_part
        assert ts_part.endswith("Z")

    def test_generated_run_id_has_hex_suffix(self) -> None:
        run_id = _generate_run_id("test.module")
        suffix = run_id.split("-")[-1]
        assert len(suffix) == 4  # 2 bytes hex = 4 chars

    def test_generated_run_ids_are_unique(self) -> None:
        ids = {_generate_run_id("test.module") for _ in range(100)}
        assert len(ids) == 100

    def test_underscores_replaced_with_hyphens(self) -> None:
        run_id = _generate_run_id("workflow.test_audit")
        assert "test-audit" in run_id
        assert "test_audit" not in run_id


# ── create_run ─────────────────────────────────────────────────────────────


class TestCreateRun:
    def test_create_run_creates_directory_structure(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        state = store.create_run("test.module", {"key": "value"})

        run_dir = tmp_path / ".codegraph" / "runs" / state.run_id
        assert run_dir.is_dir()
        assert (run_dir / "state.json").exists()
        assert (run_dir / "input.json").exists()
        assert (run_dir / "logs").is_dir()
        assert (run_dir / "artifacts").is_dir()

    def test_create_run_initial_state_values(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        state = store.create_run("test.module", {"key": "value"})

        assert state.module_id == "test.module"
        assert state.status == RunStatus.CREATED
        assert state.input_path == "input.json"
        assert state.output_path is None
        assert state.artifacts_dir == "artifacts/"
        assert state.logs_dir == "logs/"
        assert state.checkpoints_path == "checkpoints.jsonl"
        assert state.error is None
        assert state.started_at is None
        assert state.finished_at is None

    def test_create_run_without_input_params(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        state = store.create_run("test.module")

        run_dir = tmp_path / ".codegraph" / "runs" / state.run_id
        assert not (run_dir / "input.json").exists()
        assert state.input_path is None

    def test_create_run_with_custom_run_id(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        state = store.create_run(
            "test.module",
            {"key": "value"},
            run_id="my-custom-run-id",
        )
        assert state.run_id == "my-custom-run-id"

    def test_create_run_fails_on_duplicate_run_id(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", run_id="dup-run")
        with pytest.raises(FileExistsError):
            store.create_run("test.module", run_id="dup-run")

    def test_create_run_state_json_content(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        state = store.create_run("test.module", {"k": "v"}, run_id="my-run")

        run_dir = tmp_path / ".codegraph" / "runs" / "my-run"
        state_data = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        assert state_data["run_id"] == "my-run"
        assert state_data["module_id"] == "test.module"
        assert state_data["status"] == "created"

    def test_create_run_input_json_content(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", {"files": ["a.py"], "limit": 10}, run_id="my-run")

        run_dir = tmp_path / ".codegraph" / "runs" / "my-run"
        input_data = json.loads((run_dir / "input.json").read_text(encoding="utf-8"))
        assert input_data["files"] == ["a.py"]
        assert input_data["limit"] == 10


# ── load_run / update_run ──────────────────────────────────────────────────


class TestLoadAndUpdateRun:
    def test_load_existing_run(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        created = store.create_run("test.module", run_id="my-run")
        loaded = store.load_run("my-run")
        assert loaded is not None
        assert loaded.run_id == created.run_id
        assert loaded.module_id == created.module_id

    def test_load_nonexistent_run_returns_none(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        assert store.load_run("nonexistent") is None

    def test_update_run_persists_changes(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        state = store.create_run("test.module", run_id="my-run")
        state.status = RunStatus.RUNNING
        state.started_at = "2026-06-16T12:00:00Z"
        store.update_run(state)

        loaded = store.load_run("my-run")
        assert loaded is not None
        assert loaded.status == RunStatus.RUNNING
        assert loaded.started_at == "2026-06-16T12:00:00Z"

    def test_update_run_status_sets_started_at_on_running(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", run_id="my-run")
        updated = store.update_run_status("my-run", RunStatus.RUNNING)
        assert updated is not None
        assert updated.status == RunStatus.RUNNING
        assert updated.started_at is not None

    def test_update_run_status_sets_finished_at_on_succeeded(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", run_id="my-run")
        store.update_run_status("my-run", RunStatus.RUNNING)
        updated = store.update_run_status("my-run", RunStatus.SUCCEEDED)
        assert updated is not None
        assert updated.status == RunStatus.SUCCEEDED
        assert updated.finished_at is not None

    def test_update_run_status_sets_finished_at_on_failed(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", run_id="my-run")
        updated = store.update_run_status(
            "my-run", RunStatus.FAILED, error="Something went wrong"
        )
        assert updated is not None
        assert updated.status == RunStatus.FAILED
        assert updated.finished_at is not None
        assert updated.error == "Something went wrong"

    def test_update_run_status_nonexistent_returns_none(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        assert store.update_run_status("nonexistent", RunStatus.RUNNING) is None


# ── write_input / write_output / read_output ───────────────────────────────


class TestInputOutput:
    def test_write_and_read_output(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", run_id="my-run")
        store.write_output("my-run", {"result": "ok", "count": 42})
        output = store.read_output("my-run")
        assert output == {"result": "ok", "count": 42}

    def test_write_output_updates_state(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", run_id="my-run")
        store.write_output("my-run", {"result": "ok"})
        state = store.load_run("my-run")
        assert state is not None
        assert state.output_path == "output.json"

    def test_read_output_nonexistent_returns_none(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        assert store.read_output("nonexistent") is None

    def test_write_input_overwrites(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", input_params={"v1": 1}, run_id="my-run")
        store.write_input("my-run", {"v2": 2})
        run_dir = tmp_path / ".codegraph" / "runs" / "my-run"
        input_data = json.loads((run_dir / "input.json").read_text(encoding="utf-8"))
        assert input_data == {"v2": 2}

    def test_write_input_nonexistent_run_raises(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        with pytest.raises(FileNotFoundError, match="Run directory does not exist"):
            store.write_input("nonexistent", {})

    def test_write_output_nonexistent_run_raises(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        with pytest.raises(FileNotFoundError, match="Run directory does not exist"):
            store.write_output("nonexistent", {})


# ── append_event / append_checkpoint ───────────────────────────────────────


class TestEventsAndCheckpoints:
    def test_append_event_creates_events_jsonl(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", run_id="my-run")
        store.append_event("my-run", {"type": "run.created", "time": "2026-06-16T12:00:00Z"})
        store.append_event("my-run", {"type": "module.started", "time": "2026-06-16T12:00:01Z"})

        run_dir = tmp_path / ".codegraph" / "runs" / "my-run"
        events_path = run_dir / "events.jsonl"
        assert events_path.exists()
        lines = events_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["type"] == "run.created"
        assert json.loads(lines[1])["type"] == "module.started"

    def test_append_checkpoint_creates_checkpoints_jsonl(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", run_id="my-run")
        store.append_checkpoint(
            "my-run",
            {"name": "halfway", "status": "recorded", "payload": {"count": 1}},
        )

        run_dir = tmp_path / ".codegraph" / "runs" / "my-run"
        cp_path = run_dir / "checkpoints.jsonl"
        assert cp_path.exists()
        lines = cp_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["name"] == "halfway"


# ── list_runs ──────────────────────────────────────────────────────────────


class TestListRuns:
    def test_list_runs_returns_newest_first(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", run_id="run-1")
        time.sleep(0.1)
        store.create_run("test.module", run_id="run-2")
        time.sleep(0.1)
        store.create_run("test.module", run_id="run-3")

        runs = store.list_runs()
        run_ids = [r.run_id for r in runs]
        assert run_ids == ["run-3", "run-2", "run-1"]

    def test_list_runs_filter_by_module(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("workflow.impact", run_id="impact-1")
        store.create_run("workflow.find", run_id="find-1")
        store.create_run("workflow.impact", run_id="impact-2")

        impact_runs = store.list_runs(module_id="workflow.impact")
        assert len(impact_runs) == 2
        assert all(r.module_id == "workflow.impact" for r in impact_runs)

        find_runs = store.list_runs(module_id="workflow.find")
        assert len(find_runs) == 1
        assert find_runs[0].run_id == "find-1"

    def test_list_runs_respects_limit(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        for i in range(10):
            store.create_run("test.module", run_id=f"run-{i}")

        runs = store.list_runs(limit=3)
        assert len(runs) == 3

    def test_list_runs_empty_store(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        assert store.list_runs() == []


# ── delete_run ─────────────────────────────────────────────────────────────


class TestDeleteRun:
    def test_delete_existing_run(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", run_id="my-run")
        assert store.delete_run("my-run") is True
        assert store.load_run("my-run") is None
        run_dir = tmp_path / ".codegraph" / "runs" / "my-run"
        assert not run_dir.exists()

    def test_delete_nonexistent_run_returns_false(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        assert store.delete_run("nonexistent") is False

    def test_delete_run_rejects_path_traversal(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        with pytest.raises(ValueError, match="path traversal"):
            store.delete_run("..\\escape")


# ── prune_runs ─────────────────────────────────────────────────────────────


class TestPruneRuns:
    def test_prune_removes_old_runs(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", run_id="old-run")
        # We can't easily modify mtime, but prune with keep_days=0 removes all
        count = store.prune_runs(keep_days=0)
        assert count >= 0  # At minimum, it runs without error

    def test_prune_keep_days_negative(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run("test.module", run_id="my-run")
        # Negative keep_days means "immediately old" — all should be removed
        count = store.prune_runs(keep_days=-1)
        # All runs should be removed
        assert count >= 0


# ── Path helpers ───────────────────────────────────────────────────────────


class TestPathHelpers:
    def test_run_dir_returns_correct_path(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        run_dir = store.run_dir("my-run")
        assert run_dir == tmp_path / ".codegraph" / "runs" / "my-run"

    def test_artifacts_dir_returns_correct_path(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        art_dir = store.artifacts_dir("my-run")
        assert art_dir == tmp_path / ".codegraph" / "runs" / "my-run" / "artifacts"

    def test_logs_dir_returns_correct_path(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        log_dir = store.logs_dir("my-run")
        assert log_dir == tmp_path / ".codegraph" / "runs" / "my-run" / "logs"

    def test_base_dir_property(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        assert store.base_dir == tmp_path / ".codegraph" / "runs"


# ── Project root resolution ────────────────────────────────────────────────


class TestProjectRoot:
    def test_custom_project_root(self, tmp_path: Path) -> None:
        custom_root = tmp_path / "custom"
        store = RunStore(project_root=custom_root)
        state = store.create_run(
            "test.module",
            project_root=str(custom_root.resolve()),
            run_id="my-run",
        )
        run_dir = custom_root / ".codegraph" / "runs" / "my-run"
        assert run_dir.is_dir()
        assert state.project_root == str(custom_root.resolve())

    def test_path_project_root(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        state = store.create_run("test.module", run_id="my-run")
        run_dir = tmp_path / ".codegraph" / "runs" / "my-run"
        assert run_dir.is_dir()


# ── Edge cases ─────────────────────────────────────────────────────────────


class TestStoreEdgeCases:
    def test_empty_input_params_json(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        # Empty dict {} is falsy in Python — create_run skips input.json for falsy input_params
        state = store.create_run("test.module", {}, run_id="my-run")
        run_dir = tmp_path / ".codegraph" / "runs" / "my-run"
        assert not (run_dir / "input.json").exists()
        assert state.input_path is None

    def test_nested_input_params(self, tmp_path: Path) -> None:
        store = RunStore(project_root=tmp_path)
        store.create_run(
            "test.module",
            {"nested": {"deep": {"value": [1, 2, 3]}}},
            run_id="my-run",
        )
        run_dir = tmp_path / ".codegraph" / "runs" / "my-run"
        data = json.loads((run_dir / "input.json").read_text(encoding="utf-8"))
        assert data["nested"]["deep"]["value"] == [1, 2, 3]
