"""Tests for legacy CLI workflow commands.

Verifies that old CLI commands still work after harness migration:
- codegraph workflow impact
- codegraph workflow test-audit
- codegraph workflow explain
- codegraph workflow find

Each command should delegate to HarnessRunner internally and produce
output without crashing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli.main import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def indexed_project(tmp_path: Path) -> Path:
    """Create a minimal indexed Python project."""
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


# ── Legacy workflow impact ─────────────────────────────────────────────────


class TestLegacyWorkflowImpact:
    def test_workflow_impact_still_available(
        self,
        runner: CliRunner,
        indexed_project: Path,
    ) -> None:
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--change-type", "refactor",
                "--root", str(indexed_project),
                "--format", "markdown",
            ],
        )

        assert result.exit_code == 0
        # Should produce a report (markdown or JSON)
        assert len(result.output) > 0

    def test_workflow_impact_json_format(
        self,
        runner: CliRunner,
        indexed_project: Path,
    ) -> None:
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--change-type", "refactor",
                "--root", str(indexed_project),
                "--format", "json",
            ],
        )

        assert result.exit_code == 0
        assert "risk_level" in result.output or "medium" in result.output

    def test_workflow_impact_without_files_or_symbols_fails(
        self,
        runner: CliRunner,
        indexed_project: Path,
    ) -> None:
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--change-type", "refactor",
                "--root", str(indexed_project),
            ],
        )

        assert result.exit_code == 1
        assert "error" in result.output.lower() or "Error" in result.output

    def test_workflow_impact_invalid_change_type(
        self,
        runner: CliRunner,
        indexed_project: Path,
    ) -> None:
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--change-type", "invalid_type",
                "--root", str(indexed_project),
            ],
        )

        assert result.exit_code == 1
        assert "Invalid" in result.output


# ── Legacy workflow test-audit ─────────────────────────────────────────────


class TestLegacyWorkflowTestAudit:
    def test_workflow_test_audit_still_available(
        self,
        runner: CliRunner,
        indexed_project: Path,
    ) -> None:
        result = runner.invoke(
            app,
            [
                "workflow", "test-audit",
                "--root", str(indexed_project),
                "--format", "markdown",
            ],
        )

        assert result.exit_code == 0
        assert len(result.output) > 0

    def test_workflow_test_audit_json_format(
        self,
        runner: CliRunner,
        indexed_project: Path,
    ) -> None:
        result = runner.invoke(
            app,
            [
                "workflow", "test-audit",
                "--root", str(indexed_project),
                "--format", "json",
            ],
        )

        assert result.exit_code == 0
        assert "ok" in result.output.lower() or "summary" in result.output.lower()


# ── Legacy workflow explain ────────────────────────────────────────────────


class TestLegacyWorkflowExplain:
    def test_workflow_explain_still_available(
        self,
        runner: CliRunner,
        indexed_project: Path,
    ) -> None:
        result = runner.invoke(
            app,
            [
                "workflow", "explain",
                "--symbol", "greet",
                "--root", str(indexed_project),
                "--format", "markdown",
            ],
        )

        assert result.exit_code == 0
        assert len(result.output) > 0

    def test_workflow_explain_json_format(
        self,
        runner: CliRunner,
        indexed_project: Path,
    ) -> None:
        result = runner.invoke(
            app,
            [
                "workflow", "explain",
                "--symbol", "greet",
                "--root", str(indexed_project),
                "--format", "json",
            ],
        )

        assert result.exit_code == 0


# ── Legacy workflow find ───────────────────────────────────────────────────


class TestLegacyWorkflowFind:
    def test_workflow_find_still_available(
        self,
        runner: CliRunner,
        indexed_project: Path,
    ) -> None:
        result = runner.invoke(
            app,
            [
                "workflow", "find",
                "greet",  # positional argument, not --query
                "--root", str(indexed_project),
                "--format", "markdown",
            ],
        )

        assert result.exit_code == 0
        assert len(result.output) > 0

    def test_workflow_find_json_format(
        self,
        runner: CliRunner,
        indexed_project: Path,
    ) -> None:
        result = runner.invoke(
            app,
            [
                "workflow", "find",
                "greet",  # positional argument, not --query
                "--root", str(indexed_project),
                "--format", "json",
            ],
        )

        assert result.exit_code == 0
