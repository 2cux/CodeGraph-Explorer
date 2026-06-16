"""Tests for harness workflow.impact module.

Covers:
- harness run workflow.impact success
- run directory creation (.codegraph/runs/<run-id>)
- report.md exists
- report.json exists
- output.json exists
- output structure (ok, workflow, risk_level, affected_files, etc.)
- state.json status is succeeded
- events.jsonl records lifecycle events
- run with custom input (files, symbols, change_type)
- run with minimal input (empty)
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
    """Ensure builtin modules are registered for harness runner tests."""
    monkeypatch.setattr("codegraph.harness.registry._MODULES", {}, raising=False)
    reset_builtin_modules_registered()
    register_builtin_modules()


# ── Harness runner success ─────────────────────────────────────────────────


class TestWorkflowImpactSuccess:
    def test_harness_run_workflow_impact_succeeds(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.impact",
            {"files": ["greeter.py"], "change_type": "refactor"},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"
        assert result.module_id == "workflow.impact"
        assert result.run_id
        assert result.output is not None
        assert result.output["ok"] is True
        assert result.output["workflow"] == "impact"

    def test_run_creates_run_directory(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.impact",
            {"files": ["greeter.py"], "change_type": "refactor"},
            project_root=indexed_project,
        )

        run_dir = indexed_project / ".codegraph" / "runs" / result.run_id
        assert run_dir.is_dir()
        assert (run_dir / "state.json").exists()
        assert (run_dir / "output.json").exists()
        assert (run_dir / "events.jsonl").exists()
        assert (run_dir / "manifest.json").exists()

    def test_report_md_exists(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.impact",
            {"files": ["greeter.py"], "change_type": "refactor"},
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
            "workflow.impact",
            {"files": ["greeter.py"], "change_type": "refactor"},
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
            "workflow.impact",
            {"files": ["greeter.py"], "change_type": "refactor"},
            project_root=indexed_project,
        )

        run_dir = indexed_project / ".codegraph" / "runs" / result.run_id
        output_data = json.loads((run_dir / "output.json").read_text(encoding="utf-8"))
        assert output_data["ok"] is True
        assert "risk_level" in output_data


# ── Output structure ───────────────────────────────────────────────────────


class TestWorkflowImpactOutputStructure:
    def test_output_has_required_fields(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.impact",
            {"files": ["greeter.py"], "change_type": "refactor"},
            project_root=indexed_project,
        )

        output = result.output
        assert output is not None
        assert "ok" in output
        assert "workflow" in output
        assert "risk_level" in output
        assert "impact_summary" in output
        assert "affected_files" in output
        assert "warnings" in output
        assert "artifacts" in output
        assert output["artifacts"]["markdown_report"] == "artifacts/report.md"
        assert output["artifacts"]["json_report"] == "artifacts/report.json"

    def test_output_has_index_status(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.impact",
            {"files": ["greeter.py"], "change_type": "refactor"},
            project_root=indexed_project,
        )

        output = result.output
        assert output is not None
        assert "index_status" in output
        assert "status" in output["index_status"]
        assert "project_root" in output["index_status"]

    def test_artifacts_listed_in_result(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.impact",
            {"files": ["greeter.py"], "change_type": "refactor"},
            project_root=indexed_project,
        )

        assert "report.md" in result.artifacts
        assert "report.json" in result.artifacts


# ── Events ─────────────────────────────────────────────────────────────────


class TestWorkflowImpactEvents:
    def test_events_jsonl_has_lifecycle_events(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.impact",
            {"files": ["greeter.py"], "change_type": "refactor"},
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
        assert "checkpoint.recorded" in event_types
        assert "artifact.written" in event_types


# ── State ──────────────────────────────────────────────────────────────────


class TestWorkflowImpactState:
    def test_state_json_status_is_succeeded(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.impact",
            {"files": ["greeter.py"], "change_type": "refactor"},
            project_root=indexed_project,
        )

        run_dir = indexed_project / ".codegraph" / "runs" / result.run_id
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        assert state["status"] == "succeeded"
        assert state["output_path"] == "output.json"
        assert state["module_id"] == "workflow.impact"


# ── Input variations ───────────────────────────────────────────────────────


class TestWorkflowImpactInputVariations:
    def test_run_with_symbols(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.impact",
            {"symbols": ["greet"], "change_type": "bugfix"},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"
        output = result.output
        assert output is not None
        # planned_symbols is a list of resolved symbol dicts
        planned = output.get("planned_symbols", [])
        assert len(planned) > 0
        # Each planned symbol should have file and name keys
        assert any(
            p.get("name") == "greet" or "greet" in str(p)
            for p in planned
        )

    def test_run_with_minimal_input(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.impact",
            {},
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"
        output = result.output
        assert output is not None
        assert output["ok"] is True

    def test_run_with_include_tests_false(
        self,
        indexed_project: Path,
        registered_modules: None,
    ) -> None:
        runner = HarnessRunner()
        result = runner.run(
            "workflow.impact",
            {
                "files": ["greeter.py"],
                "change_type": "refactor",
                "include_tests": False,
            },
            project_root=indexed_project,
        )

        assert result.status.value == "succeeded"
