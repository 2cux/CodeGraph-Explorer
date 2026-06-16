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
class Greeter:
    def greet(self, name: str) -> str:
        return format_greeting(name)


def format_greeting(name: str) -> str:
    return f"Hello, {name}!"
""".strip(),
        encoding="utf-8",
    )
    (proj / "test_greeter.py").write_text(
        """
def test_greet():
    assert True
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["init", str(proj), "--no-hook"])
    assert result.exit_code == 0, result.output
    return proj


def test_workflow_find_harness_writes_expected_artifacts(indexed_project: Path) -> None:
    result = HarnessRunner().run(
        "workflow.find",
        {
            "query": "greet",
            "types": [],
            "paths": [],
            "limit": 10,
            "include_details": True,
            "include_snippets": False,
        },
        project_root=indexed_project,
        run_id="workflow-find-run",
    )

    assert result.status.value == "succeeded"
    assert isinstance(result.output, dict)
    assert result.output["workflow"] == "find"
    assert {
        "results",
        "candidates",
        "reason",
        "confidence",
        "next_required_steps",
        "warnings",
    } <= set(result.output)
    assert result.output["artifacts"] == {
        "markdown_report": "artifacts/report.md",
        "json_report": "artifacts/report.json",
    }
    assert result.output["next_required_steps"] == [
        "If you plan to edit this symbol, run workflow.impact.",
        "If you need relationships, run workflow.explain or neighbors.",
    ]

    run_dir = indexed_project / ".codegraph" / "runs" / "workflow-find-run"
    report_json = run_dir / "artifacts" / "report.json"
    report_md = run_dir / "artifacts" / "report.md"

    assert report_json.exists()
    assert report_md.exists()
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert payload["workflow"] == "find"
    markdown = report_md.read_text(encoding="utf-8")
    assert "# CodeGraph Find Workflow Report" in markdown
    assert "## Required next step" in markdown
    assert "- If you plan to edit this symbol, run workflow.impact." in markdown
    assert "- If you need relationships, run workflow.explain or neighbors." in markdown


def test_workflow_find_json_output_does_not_mix_plain_text(indexed_project: Path) -> None:
    runner = CliRunner()
    out_path = indexed_project / "find.json"

    result = runner.invoke(
        app,
        [
            "workflow",
            "find",
            "greet",
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
    assert payload["workflow"] == "find"
    assert payload["input"]["query"] == "greet"


def test_workflow_find_json_output_conflict_returns_json(indexed_project: Path) -> None:
    runner = CliRunner()
    out_path = indexed_project / "find.json"
    out_path.write_text("existing", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "workflow",
            "find",
            "greet",
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
    assert payload["workflow"] == "find"
    assert "already exists" in payload["error"]


def test_workflow_find_include_tests_true_keeps_test_symbols(indexed_project: Path) -> None:
    result = HarnessRunner().run(
        "workflow.find",
        {
            "query": "test_greet",
            "include_tests": True,
            "include_details": True,
        },
        project_root=indexed_project,
        run_id="workflow-find-tests-run",
    )

    assert result.status.value == "succeeded"
    symbols = [item["symbol"] for item in result.output["results"]]
    assert "test_greet" in symbols


def test_workflow_find_limit_above_twenty_is_respected(tmp_path: Path) -> None:
    proj = tmp_path / "big_proj"
    proj.mkdir()
    lines = []
    for index in range(30):
        lines.append(f"def alpha_{index}():")
        lines.append(f"    return {index}")
        lines.append("")
    (proj / "many_symbols.py").write_text("\n".join(lines).strip(), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["init", str(proj), "--no-hook"])
    assert result.exit_code == 0, result.output

    run_result = HarnessRunner().run(
        "workflow.find",
        {
            "query": "alpha",
            "limit": 25,
            "include_tests": False,
            "include_details": True,
        },
        project_root=proj,
        run_id="workflow-find-limit-run",
    )

    assert run_result.status.value == "succeeded"
    assert len(run_result.output["results"]) == 25
    assert run_result.output["input"]["limit"] == 25
