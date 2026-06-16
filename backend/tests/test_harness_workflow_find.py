"""Tests for harness workflow.find module.

Covers:
- harness run workflow.find success
- run directory creation (.codegraph/runs/<run-id>)
- report.md exists
- report.json exists
- output.json exists
- output structure (ok, workflow, results, candidates, reason, confidence, etc.)
- state.json status is succeeded
- events.jsonl records lifecycle events
- run with type/path filters
- run with include_details/include_snippets flags
- error when query is empty
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli.main import app
from codegraph.harness.bootstrap import register_builtin_modules
from codegraph.harness.registry import (
    reset_builtin_modules_registered,
)
from codegraph.harness.runner import HarnessRunner


@pytest.fixture
def indexed_project(tmp_path: Path) -> Path:
    """Create a minimal indexed Python project for workflow tests."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "greeter.py").write_text(
        """
def format_greeting(name: str) -> str:
    return f"Hello, {name}!"

def greet(name: str) -> str:
    return format_greeting(name)
""".strip(),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["init", str(proj), "--no-hook"])
    assert result.exit_code == 0, result.output
    return proj


@pytest.fixture
def registered_modules(monkeypatch) -> None:
    """Ensure builtin modules are registered."""
    monkeypatch.setattr("codegraph.harness.registry._MODULES", {}, raising=False)
    reset_builtin_modules_registered()
    register_builtin_modules()


# ── Harness runner success ─────────────────────────────────────────────────


class TestWorkflowFindSuccess:
    def test_harness_run_workflow_find_succeeds(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet"},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"
        assert result.module_id == "workflow.find"
        assert result.run_id
        assert result.output is not None
        assert result.output["ok"] is True
        assert result.output["workflow"] == "find"

    def test_run_creates_run_directory(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet"},
            project_root=indexed_project,
        )

        run_dir = indexed_project / ".codegraph" / "runs" / result.run_id
        assert run_dir.is_dir()
        assert (run_dir / "state.json").exists()
        assert (run_dir / "output.json").exists()

    def test_report_md_exists(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet"},
            project_root=indexed_project,
        )

        run_dir = indexed_project / ".codegraph" / "runs" / result.run_id
        report_md = run_dir / "artifacts" / "report.md"
        assert report_md.exists()
        content = report_md.read_text(encoding="utf-8")
        assert len(content) > 0

    def test_report_json_exists(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet"},
            project_root=indexed_project,
        )

        run_dir = indexed_project / ".codegraph" / "runs" / result.run_id
        report_json = run_dir / "artifacts" / "report.json"
        assert report_json.exists()
        data = json.loads(report_json.read_text(encoding="utf-8"))
        assert data["ok"] is True

    def test_output_json_exists(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet"},
            project_root=indexed_project,
        )

        run_dir = indexed_project / ".codegraph" / "runs" / result.run_id
        output_data = json.loads((run_dir / "output.json").read_text(encoding="utf-8"))
        assert output_data["ok"] is True


# ── Output structure ───────────────────────────────────────────────────────


class TestWorkflowFindOutputStructure:
    def test_output_has_required_fields(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet"},
            project_root=indexed_project,
        )

        output = result.output
        assert output is not None
        assert "ok" in output
        assert "workflow" in output
        assert "results" in output
        assert "candidates" in output
        assert "reason" in output
        assert "confidence" in output
        assert "total" in output
        assert "next_required_steps" in output
        assert "warnings" in output
        assert "artifacts" in output

    def test_results_is_list(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet"},
            project_root=indexed_project,
        )

        output = result.output
        assert isinstance(output["results"], list)

    def test_total_matches_results_length(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet"},
            project_root=indexed_project,
        )

        output = result.output
        assert output["total"] >= len(output["results"])


# ── Events ─────────────────────────────────────────────────────────────────


class TestWorkflowFindEvents:
    def test_events_jsonl_has_lifecycle_events(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet"},
            project_root=indexed_project,
        )

        run_dir = indexed_project / ".codegraph" / "runs" / result.run_id
        events_path = run_dir / "events.jsonl"
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        event_types = [e["type"] for e in events]
        assert "run.created" in event_types
        assert "module.started" in event_types
        assert "module.finished" in event_types


# ── State ──────────────────────────────────────────────────────────────────


class TestWorkflowFindState:
    def test_state_json_status_is_succeeded(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet"},
            project_root=indexed_project,
        )

        run_dir = indexed_project / ".codegraph" / "runs" / result.run_id
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        assert state["status"] == "succeeded"
        assert state["module_id"] == "workflow.find"


# ── Input validation ───────────────────────────────────────────────────────


class TestWorkflowFindInputValidation:
    def test_empty_query_fails(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": ""},
            project_root=indexed_project,
        )

        assert result.status.value == "failed"
        assert result.error is not None
        assert "non-empty" in result.error.lower()


# ── Input variations ───────────────────────────────────────────────────────


class TestWorkflowFindInputVariations:
    def test_with_types_filter(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet", "types": ["function"]},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"

    def test_with_paths_filter(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet", "paths": ["greeter.py"]},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"

    def test_with_include_snippets_true(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet", "include_snippets": True},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"

    def test_with_include_tests_false(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet", "include_tests": False},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"

    def test_with_custom_limit(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "greet", "limit": 5},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"

    def test_with_no_such_symbol_query(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.find",
            {"query": "xyz_nonexistent_symbol_12345"},
            project_root=indexed_project,
        )

        # Should still succeed even with zero results
        assert result.status.value == "succeeded"
        assert result.output is not None
        assert result.output["total"] == 0
