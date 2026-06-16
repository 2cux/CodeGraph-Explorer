"""Tests for harness workflow.test_audit module.

Covers:
- harness run workflow.test_audit success
- run directory creation (.codegraph/runs/<run-id>)
- report.md exists
- report.json exists
- output.json exists
- output structure (ok, workflow, summary, symbols_without_tests, etc.)
- state.json status is succeeded
- events.jsonl records lifecycle events
- run with custom paths/types filters
- run with include_low_confidence flag
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


class TestWorkflowTestAuditSuccess:
    def test_harness_run_workflow_test_audit_succeeds(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.test_audit",
            {},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"
        assert result.module_id == "workflow.test_audit"
        assert result.run_id
        assert result.output is not None
        assert result.output["ok"] is True
        assert result.output["workflow"] == "test-audit"

    def test_run_creates_run_directory(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.test_audit",
            {},
            project_root=indexed_project,
        )

        run_dir = indexed_project / ".codegraph" / "runs" / result.run_id
        assert run_dir.is_dir()
        assert (run_dir / "state.json").exists()
        assert (run_dir / "output.json").exists()
        assert (run_dir / "events.jsonl").exists()

    def test_report_md_exists(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.test_audit",
            {},
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
            "workflow.test_audit",
            {},
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
            "workflow.test_audit",
            {},
            project_root=indexed_project,
        )

        run_dir = indexed_project / ".codegraph" / "runs" / result.run_id
        output_data = json.loads((run_dir / "output.json").read_text(encoding="utf-8"))
        assert output_data["ok"] is True
        assert "summary" in output_data


# ── Output structure ───────────────────────────────────────────────────────


class TestWorkflowTestAuditOutputStructure:
    def test_output_has_required_fields(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.test_audit",
            {},
            project_root=indexed_project,
        )

        output = result.output
        assert output is not None
        assert "ok" in output
        assert "workflow" in output
        assert "summary" in output
        assert "warnings" in output
        assert "heuristic_coverage_disclaimer" in output
        assert "artifacts" in output

    def test_summary_has_coverage_counts(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.test_audit",
            {},
            project_root=indexed_project,
        )

        output = result.output
        assert output is not None
        summary = output.get("summary", {})
        assert "production_symbols_checked" in summary
        assert "symbols_without_test_signal" in summary


# ── Events ─────────────────────────────────────────────────────────────────


class TestWorkflowTestAuditEvents:
    def test_events_jsonl_has_lifecycle_events(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.test_audit",
            {},
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


class TestWorkflowTestAuditState:
    def test_state_json_status_is_succeeded(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.test_audit",
            {},
            project_root=indexed_project,
        )

        run_dir = indexed_project / ".codegraph" / "runs" / result.run_id
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        assert state["status"] == "succeeded"
        assert state["module_id"] == "workflow.test_audit"


# ── Input variations ───────────────────────────────────────────────────────


class TestWorkflowTestAuditInputVariations:
    def test_run_with_paths_filter(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.test_audit",
            {"paths": ["greeter.py"]},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"

    def test_run_with_types_filter(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.test_audit",
            {"types": ["function"]},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"

    def test_run_with_include_low_confidence(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.test_audit",
            {"include_low_confidence": False},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"

    def test_run_with_limit(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.test_audit",
            {"limit": 5},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"
