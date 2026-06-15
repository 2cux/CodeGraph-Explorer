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
    target = proj / "backend" / "codegraph" / "graph"
    target.mkdir(parents=True)
    (target / "coverage_gaps.py").write_text(
        """
def uncovered_symbol() -> str:
    return "gap"
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["init", str(proj), "--no-hook"])
    assert result.exit_code == 0, result.output
    return proj


def test_workflow_test_audit_harness_writes_expected_artifacts(
    indexed_project: Path,
) -> None:
    result = HarnessRunner().run(
        "workflow.test_audit",
        {"paths": ["backend/codegraph/**"]},
        project_root=indexed_project,
        run_id="workflow-test-audit-run",
    )

    assert result.status.value == "succeeded"
    assert isinstance(result.output, dict)
    assert result.output["workflow"] == "test-audit"
    assert result.output["artifacts"] == {
        "markdown_report": "artifacts/report.md",
        "json_report": "artifacts/report.json",
    }
    assert "heuristic graph signal" in result.output["heuristic_coverage_disclaimer"]

    run_dir = indexed_project / ".codegraph" / "runs" / "workflow-test-audit-run"
    report_json = run_dir / "artifacts" / "report.json"
    report_md = run_dir / "artifacts" / "report.md"

    assert report_json.exists()
    assert report_md.exists()
    assert json.loads(report_json.read_text(encoding="utf-8"))["workflow"] == "test-audit"
    markdown = report_md.read_text(encoding="utf-8")
    assert "## Coverage Gaps Summary" in markdown
    assert "## Top Uncovered Production Symbols" in markdown
    assert "## Files Without Test Signals" in markdown
    assert "## Heuristic Coverage Disclaimer" in markdown


def test_workflow_test_audit_json_output_does_not_mix_plain_text(
    indexed_project: Path,
) -> None:
    runner = CliRunner()
    out_path = indexed_project / "test-audit.json"

    result = runner.invoke(
        app,
        [
            "workflow",
            "test-audit",
            "--paths",
            "backend/codegraph/**",
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
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["workflow"] == "test-audit"
    assert payload["path_resolution"]["resolved_file_count"] >= 1


def test_workflow_test_audit_reports_missing_path_warning(indexed_project: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "workflow",
            "test-audit",
            "--paths",
            "backend/codegraph/missing.py,backend/codegraph/graph/coverage_gaps.py",
            "--root",
            str(indexed_project),
        ],
    )

    assert result.exit_code == 0
    assert "## Warnings" in result.output
    assert "missing.py" in result.output


def test_workflow_test_audit_exact_file_path_scope(indexed_project: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "workflow",
            "test-audit",
            "--paths",
            "backend/codegraph/graph/coverage_gaps.py",
            "--format",
            "json",
            "--root",
            str(indexed_project),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["coverage_gaps_summary"]["production_symbols_checked"] >= 1
    assert payload["path_resolution"]["resolved_file_count"] == 1
    assert all(
        item["file"] == "backend/codegraph/graph/coverage_gaps.py"
        for item in payload["top_uncovered_production_symbols"]
    )
