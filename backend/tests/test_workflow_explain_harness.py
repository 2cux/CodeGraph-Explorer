from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli.main import app
from codegraph.graph.models import GraphNode, Location, NodeType
from codegraph.graph.store import GraphStore
from codegraph.harness import HarnessRunner
from codegraph.workflow import run_explain


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


def test_workflow_explain_harness_writes_expected_artifacts(indexed_project: Path) -> None:
    result = HarnessRunner().run(
        "workflow.explain",
        {"symbol": "greet", "include_neighbors": True, "include_snippets": True},
        project_root=indexed_project,
        run_id="workflow-explain-run",
    )

    assert result.status.value == "succeeded"
    assert isinstance(result.output, dict)
    assert result.output["workflow"] == "explain"
    assert result.output["target"]["kind"] == "symbol"
    assert {
        "target",
        "summary",
        "confidence",
        "evidence",
        "relationships",
        "test_signal",
        "warnings",
    } <= set(result.output)
    assert result.output["artifacts"] == {
        "markdown_report": "artifacts/report.md",
        "json_report": "artifacts/report.json",
    }

    run_dir = indexed_project / ".codegraph" / "runs" / "workflow-explain-run"
    report_json = run_dir / "artifacts" / "report.json"
    report_md = run_dir / "artifacts" / "report.md"

    assert report_json.exists()
    assert report_md.exists()
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert payload["workflow"] == "explain"
    markdown = report_md.read_text(encoding="utf-8")
    assert "# CodeGraph Explain Workflow Report" in markdown
    assert "## Summary" in markdown
    assert "## Relationships" in markdown


def test_workflow_explain_json_output_does_not_mix_plain_text(indexed_project: Path) -> None:
    runner = CliRunner()
    out_path = indexed_project / "explain.json"

    result = runner.invoke(
        app,
        [
            "workflow",
            "explain",
            "--symbol",
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
    assert payload["workflow"] == "explain"
    assert payload["target"]["symbol"] == "greet"


def test_workflow_explain_json_output_conflict_returns_json(indexed_project: Path) -> None:
    runner = CliRunner()
    out_path = indexed_project / "explain.json"
    out_path.write_text("existing", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "workflow",
            "explain",
            "--symbol",
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
    assert payload["workflow"] == "explain"
    assert "already exists" in payload["error"]


def test_workflow_explain_file_relationship_counts_are_not_truncated(
    tmp_path: Path,
) -> None:
    proj = tmp_path / "file_rel_proj"
    proj.mkdir()
    (proj / "target.py").write_text(
        """
def target() -> str:
    return "ok"
""".strip(),
        encoding="utf-8",
    )
    (proj / "callers.py").write_text(
        """
from target import target

def caller_1():
    return target()

def caller_2():
    return target()

def caller_3():
    return target()

def caller_4():
    return target()

def caller_5():
    return target()

def caller_6():
    return target()
""".strip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    init_result = runner.invoke(app, ["init", str(proj), "--no-hook"])
    assert init_result.exit_code == 0, init_result.output

    result = HarnessRunner().run(
        "workflow.explain",
        {"file": "target.py", "include_neighbors": True},
        project_root=proj,
        run_id="workflow-explain-file-rel-run",
    )

    assert result.status.value == "succeeded"
    relationships = result.output["relationships"]
    assert relationships["callers_count"] == 6
    assert len(relationships["top_callers"]) == 5


def test_run_explain_does_not_read_snippet_outside_project_root(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()
    outside_file = tmp_path / "secret.py"
    outside_file.write_text("TOP_SECRET = 1\n", encoding="utf-8")

    store = GraphStore()
    store.add_node(
        GraphNode(
            id="../secret.py::leak",
            type=NodeType.function,
            name="leak",
            file_path="../secret.py",
            location=Location(line_start=1, line_end=1),
        )
    )

    result = run_explain(
        store=store,
        symbol="leak",
        include_snippet=True,
        include_tests=False,
        include_relationships=False,
        project_root=str(project_root),
    )

    assert result["ok"] is True
    snippet = result.get("source_snippet", {})
    assert snippet.get("included") is False
    assert snippet.get("content") is None
