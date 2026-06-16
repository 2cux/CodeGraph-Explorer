"""Tests for MCP harness tools — PRD Section 26.5.

Covers MCP tool exposure and integration:
- codegraph_harness_list exposes builtin manifests
- codegraph_harness_run workflow.impact succeeds
- codegraph_harness_status can read run state
- codegraph_harness_artifacts can list artifacts
- artifact content is NOT returned by default (compact principle)
- artifact content IS returned when explicitly requested
- error handling for invalid inputs
- module allowlist enforcement
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli.main import app
from codegraph.harness.artifacts import ArtifactManager
from codegraph.harness.store import RunStore


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


@pytest.fixture
def mcp_project_root(indexed_project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set CODEGRAPH_PROJECT_ROOT for MCP helpers."""
    import codegraph.mcp_server as mcp_mod

    monkeypatch.setattr(mcp_mod, "_project_root", str(indexed_project), raising=False)
    return indexed_project


# ── Tool registration ──────────────────────────────────────────────────────


class TestMcpToolRegistration:
    def test_all_four_harness_tools_registered(self) -> None:
        """Verify that all 4 MCP harness tools are registered."""
        from codegraph.mcp_server import mcp

        registered = getattr(mcp, "_tool_manager", None)
        assert registered is not None
        names = set(registered._tools.keys())
        assert "codegraph_harness_list" in names
        assert "codegraph_harness_run" in names
        assert "codegraph_harness_status" in names
        assert "codegraph_harness_artifacts" in names

    def test_harness_list_not_empty(self) -> None:
        """Harness list should return at least the 4 stable workflow modules."""
        from codegraph.mcp_server import codegraph_harness_list

        result = codegraph_harness_list()
        assert result["ok"] is True
        modules = result["data"]["modules"]
        assert result["data"]["count"] >= 4

        module_ids = {m["id"] for m in modules}
        assert "workflow.impact" in module_ids
        assert "workflow.test_audit" in module_ids
        assert "workflow.explain" in module_ids
        assert "workflow.find" in module_ids


# ── codegraph_harness_run ──────────────────────────────────────────────────


class TestMcpHarnessRun:
    def test_run_workflow_impact_succeeds(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_run

        result = codegraph_harness_run(
            "workflow.impact",
            input={"files": ["greeter.py"], "change_type": "refactor"},
        )

        assert result["ok"] is True
        data = result["data"]
        assert data["module_id"] == "workflow.impact"
        assert data["status"] == "succeeded"
        assert data["run_id"]
        assert "summary" in data
        assert "risk=" in data["summary"]
        # output is included in run result
        assert "output" in data
        # artifacts map is included
        assert "artifacts" in data
        assert "report_md" in data["artifacts"]
        assert "report_json" in data["artifacts"]

    def test_run_workflow_test_audit_succeeds(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_run

        result = codegraph_harness_run(
            "workflow.test_audit",
            input={},
        )

        assert result["ok"] is True
        data = result["data"]
        assert data["module_id"] == "workflow.test_audit"
        assert data["status"] == "succeeded"
        assert "production_symbols_checked=" in data["summary"]

    def test_run_workflow_explain_succeeds(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_run

        result = codegraph_harness_run(
            "workflow.explain",
            input={"symbol": "greet"},
        )

        assert result["ok"] is True
        data = result["data"]
        assert data["module_id"] == "workflow.explain"
        assert data["status"] == "succeeded"
        assert "target=" in data["summary"]

    def test_run_workflow_find_succeeds(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_run

        result = codegraph_harness_run(
            "workflow.find",
            input={"query": "greet"},
        )

        assert result["ok"] is True
        data = result["data"]
        assert data["module_id"] == "workflow.find"
        assert data["status"] == "succeeded"
        assert "query=" in data["summary"]
        assert "results=" in data["summary"]

    def test_run_rejects_reserved_module(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_run

        result = codegraph_harness_run("enrich.prepare", input={})

        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"
        assert "not exposed over MCP" in result["error"]["message"]

    def test_run_rejects_unknown_module(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_run

        result = codegraph_harness_run("no.such.module", input={})

        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"


# ── codegraph_harness_status ───────────────────────────────────────────────


class TestMcpHarnessStatus:
    def test_status_reads_run_state(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_run, codegraph_harness_status

        run_result = codegraph_harness_run(
            "workflow.impact",
            input={"files": ["greeter.py"], "change_type": "refactor"},
        )
        run_id = run_result["data"]["run_id"]

        result = codegraph_harness_status(run_id)

        assert result["ok"] is True
        data = result["data"]
        assert data["run_id"] == run_id
        assert data["module_id"] == "workflow.impact"
        assert data["status"] == "succeeded"
        assert "state" in data
        assert data["state"]["status"] == "succeeded"
        # Status should NOT include the full output
        assert "output" not in data

    def test_status_nonexistent_run_returns_error(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_status

        result = codegraph_harness_status("nonexistent-run-id")

        assert result["ok"] is False
        assert result["error"]["code"] == "RUN_NOT_FOUND"


# ── codegraph_harness_artifacts ────────────────────────────────────────────


class TestMcpHarnessArtifacts:
    def test_artifacts_lists_without_content_by_default(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_artifacts, codegraph_harness_run

        run_result = codegraph_harness_run(
            "workflow.impact",
            input={"files": ["greeter.py"], "change_type": "refactor"},
        )
        run_id = run_result["data"]["run_id"]

        result = codegraph_harness_artifacts(run_id)

        assert result["ok"] is True
        data = result["data"]
        assert data["run_id"] == run_id
        assert data["content_included"] is False
        assert "artifacts" in data

        # Each artifact should NOT have content field
        for artifact in data["artifacts"]:
            assert "content" not in artifact, (
                f"Artifact {artifact['name']} should not include content by default"
            )

    def test_artifacts_reads_content_when_requested(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_artifacts, codegraph_harness_run

        run_result = codegraph_harness_run(
            "workflow.impact",
            input={"files": ["greeter.py"], "change_type": "refactor"},
        )
        run_id = run_result["data"]["run_id"]

        result = codegraph_harness_artifacts(
            run_id,
            artifact_name="report.md",
            include_content=True,
        )

        assert result["ok"] is True
        data = result["data"]
        assert data["content_included"] is True
        assert "artifact" in data
        assert "content" in data["artifact"]
        assert isinstance(data["artifact"]["content"], str)
        assert len(data["artifact"]["content"]) > 0

    def test_artifacts_requires_name_for_content_read(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_artifacts, codegraph_harness_run

        run_result = codegraph_harness_run(
            "workflow.impact",
            input={"files": ["greeter.py"], "change_type": "refactor"},
        )
        run_id = run_result["data"]["run_id"]

        # include_content without artifact_name should fail
        result = codegraph_harness_artifacts(run_id, include_content=True)

        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"

    def test_artifacts_lists_all_expected_artifacts(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_artifacts, codegraph_harness_run

        run_result = codegraph_harness_run(
            "workflow.impact",
            input={"files": ["greeter.py"], "change_type": "refactor"},
        )
        run_id = run_result["data"]["run_id"]

        result = codegraph_harness_artifacts(run_id)

        data = result["data"]
        artifact_names = [a["name"] for a in data["artifacts"]]
        assert "report.md" in artifact_names
        assert "report.json" in artifact_names

    def test_artifacts_nonexistent_run_returns_error(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_artifacts

        result = codegraph_harness_artifacts("nonexistent-run-id")

        assert result["ok"] is False
        assert result["error"]["code"] == "RUN_NOT_FOUND"

    def test_artifacts_rejects_path_traversal_name(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import codegraph_harness_artifacts, codegraph_harness_run

        run_result = codegraph_harness_run(
            "workflow.impact",
            input={"files": ["greeter.py"], "change_type": "refactor"},
        )
        run_id = run_result["data"]["run_id"]

        result = codegraph_harness_artifacts(
            run_id,
            artifact_name="..\\secret.txt",
            include_content=True,
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"


# ── Integration: full MCP workflow lifecycle ───────────────────────────────


class TestMcpFullWorkflowLifecycle:
    """Test a complete MCP harness workflow: run → status → artifacts → read content."""

    def test_full_lifecycle_impact_workflow(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import (
            codegraph_harness_artifacts,
            codegraph_harness_run,
            codegraph_harness_status,
        )

        # 1. Run
        run_result = codegraph_harness_run(
            "workflow.impact",
            input={"files": ["greeter.py"], "change_type": "refactor"},
        )
        assert run_result["ok"] is True
        run_id = run_result["data"]["run_id"]

        # 2. Status
        status = codegraph_harness_status(run_id)
        assert status["ok"] is True
        assert status["data"]["status"] == "succeeded"
        assert status["data"]["state"]["module_id"] == "workflow.impact"

        # 3. List artifacts (no content)
        artifacts = codegraph_harness_artifacts(run_id)
        assert artifacts["ok"] is True
        assert artifacts["data"]["content_included"] is False
        art_names = [a["name"] for a in artifacts["data"]["artifacts"]]
        assert "report.md" in art_names
        assert "report.json" in art_names

        # 4. Read specific artifact content
        report_md = codegraph_harness_artifacts(
            run_id,
            artifact_name="report.md",
            include_content=True,
        )
        assert report_md["ok"] is True
        assert report_md["data"]["content_included"] is True
        content = report_md["data"]["artifact"]["content"]
        assert isinstance(content, str)
        assert len(content) > 0

    def test_full_lifecycle_find_workflow(
        self,
        mcp_project_root: Path,
    ) -> None:
        from codegraph.mcp_server import (
            codegraph_harness_artifacts,
            codegraph_harness_run,
            codegraph_harness_status,
        )

        # 1. Run
        run_result = codegraph_harness_run(
            "workflow.find",
            input={"query": "greet"},
        )
        assert run_result["ok"] is True
        run_id = run_result["data"]["run_id"]

        # 2. Status
        status = codegraph_harness_status(run_id)
        assert status["ok"] is True
        assert status["data"]["status"] == "succeeded"

        # 3. List artifacts
        artifacts = codegraph_harness_artifacts(run_id)
        assert artifacts["ok"] is True
        assert artifacts["data"]["content_included"] is False

        # 4. Read report.json content
        report_json = codegraph_harness_artifacts(
            run_id,
            artifact_name="report.json",
            include_content=True,
        )
        assert report_json["ok"] is True
        assert report_json["data"]["content_included"] is True
