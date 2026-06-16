from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli.main import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


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
    result = CliRunner().invoke(app, ["init", str(proj), "--no-hook"])
    assert result.exit_code == 0, result.output
    return proj


def test_harness_list_shows_expected_modules(runner: CliRunner) -> None:
    result = runner.invoke(app, ["harness", "list"])

    assert result.exit_code == 0
    assert "workflow.impact        stable" in result.output
    assert "workflow.test_audit    stable" in result.output
    assert "workflow.explain       stable" in result.output
    assert "workflow.find          stable" in result.output
    assert "enrich.prepare         reserved" in result.output
    assert "benchmark.gate         reserved" in result.output
    assert "doctor.run             stable" in result.output


def test_harness_run_supports_input_json(
    runner: CliRunner,
    indexed_project: Path,
) -> None:
    input_path = indexed_project / "input.json"
    input_path.write_text(
        json.dumps({"files": ["greeter.py"], "change_type": "refactor"}),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "harness",
            "run",
            "workflow.impact",
            "--input",
            str(input_path),
            "--root",
            str(indexed_project),
        ],
    )

    assert result.exit_code == 0
    assert "module: workflow.impact" in result.output
    assert "status: succeeded" in result.output
    runs_dir = indexed_project / ".codegraph" / "runs"
    run_dirs = [path for path in runs_dir.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "state.json").exists()


def test_harness_status_reads_state_json(
    runner: CliRunner,
    indexed_project: Path,
) -> None:
    run_result = runner.invoke(
        app,
        [
            "harness",
            "run",
            "workflow.impact",
            "--files",
            "greeter.py",
            "--change-type",
            "refactor",
            "--root",
            str(indexed_project),
        ],
        env={"CODEGRAPH_PROJECT_ROOT": str(indexed_project)},
    )
    assert run_result.exit_code == 0

    actual_run_id = None
    for line in run_result.output.splitlines():
        if line.startswith("run_id: "):
            actual_run_id = line.split(": ", 1)[1].strip()
            break
    assert actual_run_id is not None

    result = runner.invoke(
        app,
        ["harness", "status", actual_run_id, "--root", str(indexed_project)],
    )

    assert result.exit_code == 0
    assert f"run_id: {actual_run_id}" in result.output
    assert "module: workflow.impact" in result.output
    assert "status: succeeded" in result.output
    assert "output_path: output.json" in result.output


def test_harness_artifacts_lists_run_artifacts(
    runner: CliRunner,
    indexed_project: Path,
) -> None:
    run_result = runner.invoke(
        app,
        [
            "harness",
            "run",
            "workflow.impact",
            "--files",
            "greeter.py",
            "--change-type",
            "refactor",
            "--root",
            str(indexed_project),
        ],
    )
    assert run_result.exit_code == 0

    actual_run_id = next(
        line.split(": ", 1)[1].strip()
        for line in run_result.output.splitlines()
        if line.startswith("run_id: ")
    )
    result = runner.invoke(
        app,
        ["harness", "artifacts", actual_run_id, "--root", str(indexed_project)],
    )

    assert result.exit_code == 0
    assert "report.json\tapplication/json" in result.output
    assert "report.md\ttext/markdown" in result.output


def test_harness_docs_generates_markdown(
    runner: CliRunner,
    indexed_project: Path,
) -> None:
    result = runner.invoke(
        app,
        ["harness", "docs", "--root", str(indexed_project)],
    )

    docs_path = indexed_project / "docs" / "harness-modules.md"
    assert result.exit_code == 0
    assert docs_path.exists()
    content = docs_path.read_text(encoding="utf-8")
    assert "# Harness Modules" in content
    assert "### `workflow.impact`" in content
    assert "### `doctor.run`" in content
    assert "### `enrich.validate`" in content
    assert "- Version: `1.0.0`" in content


def test_harness_status_finds_run_from_nested_directory(
    runner: CliRunner,
    indexed_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_result = runner.invoke(
        app,
        [
            "harness",
            "run",
            "workflow.impact",
            "--files",
            "greeter.py",
            "--change-type",
            "refactor",
            "--root",
            str(indexed_project),
        ],
    )
    assert run_result.exit_code == 0
    actual_run_id = next(
        line.split(": ", 1)[1].strip()
        for line in run_result.output.splitlines()
        if line.startswith("run_id: ")
    )

    nested = indexed_project / "sub" / "dir"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    result = runner.invoke(app, ["harness", "status", actual_run_id])

    assert result.exit_code == 0
    assert f"run_id: {actual_run_id}" in result.output
    assert "module: workflow.impact" in result.output


def test_harness_artifacts_finds_run_from_nested_directory(
    runner: CliRunner,
    indexed_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_result = runner.invoke(
        app,
        [
            "harness",
            "run",
            "workflow.impact",
            "--files",
            "greeter.py",
            "--change-type",
            "refactor",
            "--root",
            str(indexed_project),
        ],
    )
    assert run_result.exit_code == 0
    actual_run_id = next(
        line.split(": ", 1)[1].strip()
        for line in run_result.output.splitlines()
        if line.startswith("run_id: ")
    )

    nested = indexed_project / "deep" / "child"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    result = runner.invoke(app, ["harness", "artifacts", actual_run_id])

    assert result.exit_code == 0
    assert "report.json\tapplication/json" in result.output
    assert "report.md\ttext/markdown" in result.output


def test_harness_docs_uses_detected_project_root(
    runner: CliRunner,
    indexed_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nested = indexed_project / "pkg" / "feature"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    result = runner.invoke(app, ["harness", "docs"])

    assert result.exit_code == 0
    assert (indexed_project / "docs" / "harness-modules.md").exists()
    assert not (nested / "docs" / "harness-modules.md").exists()


def test_harness_run_unknown_module_returns_clean_error(
    runner: CliRunner,
) -> None:
    result = runner.invoke(app, ["harness", "run", "no.such.module"])

    assert result.exit_code == 1
    assert "Unknown harness module: no.such.module" in result.output
    assert "Traceback" not in result.output


def test_harness_status_invalid_run_id_returns_clean_error(
    runner: CliRunner,
    indexed_project: Path,
) -> None:
    result = runner.invoke(
        app,
        ["harness", "status", "..\\bad", "--root", str(indexed_project)],
    )

    assert result.exit_code == 1
    assert "run_id contains path traversal" in result.output
    assert "Traceback" not in result.output
