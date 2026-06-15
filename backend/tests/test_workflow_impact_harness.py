from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli.main import app
from codegraph.harness import HarnessRunner


@pytest.fixture
def indexed_project(tmp_path: Path) -> Path:
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
    runner = CliRunner()
    result = runner.invoke(app, ["init", str(proj), "--no-hook"])
    assert result.exit_code == 0, result.output
    return proj


def test_workflow_impact_harness_writes_expected_artifacts(indexed_project: Path) -> None:
    result = HarnessRunner().run(
        "workflow.impact",
        {"files": ["greeter.py"], "change_type": "refactor"},
        project_root=indexed_project,
        run_id="workflow-impact-run",
    )

    assert result.status.value == "succeeded"
    assert isinstance(result.output, dict)
    assert result.output["ok"] is True
    assert result.output["workflow"] == "impact"
    assert result.output["risk_level"] in ("low", "medium", "high", "critical", "unknown")
    assert result.output["artifacts"] == {
        "markdown_report": "artifacts/report.md",
        "json_report": "artifacts/report.json",
    }

    run_dir = indexed_project / ".codegraph" / "runs" / "workflow-impact-run"
    report_json = run_dir / "artifacts" / "report.json"
    report_md = run_dir / "artifacts" / "report.md"

    assert report_json.exists()
    assert report_md.exists()
    assert json.loads(report_json.read_text(encoding="utf-8"))["workflow"] == "impact"
    assert "# CodeGraph Impact Workflow Report" in report_md.read_text(encoding="utf-8")


def test_workflow_impact_json_output_does_not_mix_plain_text(indexed_project: Path) -> None:
    runner = CliRunner()
    out_path = indexed_project / "impact.json"

    result = runner.invoke(
        app,
        [
            "workflow",
            "impact",
            "--files",
            "greeter.py",
            "--format",
            "json",
            "--output",
            str(out_path),
            "--root",
            str(indexed_project),
        ],
    )

    assert result.exit_code == 0
    assert result.output.strip() == ""
    assert out_path.exists()
    assert json.loads(out_path.read_text(encoding="utf-8"))["workflow"] == "impact"

    runs_dir = indexed_project / ".codegraph" / "runs"
    run_artifacts = [path / "artifacts" / "report.json" for path in runs_dir.iterdir()]
    assert any(path.exists() for path in run_artifacts)


def test_workflow_impact_json_output_conflict_returns_json(indexed_project: Path) -> None:
    runner = CliRunner()
    out_path = indexed_project / "impact.json"
    out_path.write_text("existing", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "workflow",
            "impact",
            "--files",
            "greeter.py",
            "--format",
            "json",
            "--output",
            str(out_path),
            "--root",
            str(indexed_project),
        ],
    )

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["workflow"] == "impact"
    assert "already exists" in payload["error"]
