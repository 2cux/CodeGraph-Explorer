from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli.main import app
from codegraph.harness.artifacts import ArtifactManager
from codegraph.harness.store import RunStore


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


@pytest.fixture
def mcp_project_root(indexed_project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import codegraph.mcp_server as mcp_mod

    monkeypatch.setattr(mcp_mod, "_project_root", str(indexed_project), raising=False)
    return indexed_project


class TestHarnessMcpTools:
    def test_tools_registered(self):
        from codegraph.mcp_server import mcp

        registered = getattr(mcp, "_tool_manager", None)
        assert registered is not None
        names = set(registered._tools.keys())
        assert "codegraph_harness_list" in names
        assert "codegraph_harness_run" in names
        assert "codegraph_harness_status" in names
        assert "codegraph_harness_artifacts" in names

    def test_harness_list_returns_builtin_manifests(self, mcp_project_root: Path):
        from codegraph.mcp_server import codegraph_harness_list

        result = codegraph_harness_list()

        assert result["ok"] is True
        assert result["tool"] == "codegraph_harness_list"
        modules = result["data"]["modules"]
        module_ids = {item["id"] for item in modules}
        assert "workflow.impact" in module_ids
        assert "workflow.find" in module_ids
        assert "mcp.execute" in module_ids

    def test_harness_run_executes_workflow_impact(self, mcp_project_root: Path):
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
        assert "risk=" in data["summary"]
        assert "report_md" in data["artifacts"]
        assert "report_json" in data["artifacts"]

    def test_harness_run_rejects_disabled_mcp_execute(self, mcp_project_root: Path):
        from codegraph.mcp_server import codegraph_harness_run

        result = codegraph_harness_run("mcp.execute", input={})

        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"
        assert "not exposed over MCP" in result["error"]["message"]

    def test_harness_run_rejects_doctor_run(self, mcp_project_root: Path):
        from codegraph.mcp_server import codegraph_harness_run

        result = codegraph_harness_run("doctor.run", input={"repair": True})

        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"
        assert "not exposed over MCP" in result["error"]["message"]

    def test_harness_run_rejects_non_object_input(self, mcp_project_root: Path):
        from codegraph.mcp_server import codegraph_harness_run

        result = codegraph_harness_run("workflow.impact", input=["bad"])  # type: ignore[arg-type]

        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"
        assert "JSON object" in result["error"]["message"]

    def test_harness_status_reads_persisted_state(self, mcp_project_root: Path):
        from codegraph.mcp_server import codegraph_harness_run, codegraph_harness_status

        run_result = codegraph_harness_run(
            "workflow.impact",
            input={"files": ["greeter.py"], "change_type": "refactor"},
        )
        run_id = run_result["data"]["run_id"]

        result = codegraph_harness_status(run_id)

        assert result["ok"] is True
        assert result["data"]["run_id"] == run_id
        assert result["data"]["state"]["status"] == "succeeded"
        assert "output" not in result["data"]

    def test_harness_run_rejects_non_persistent_mode(self, mcp_project_root: Path):
        from codegraph.mcp_server import codegraph_harness_run

        result = codegraph_harness_run(
            "workflow.impact",
            input={"files": ["greeter.py"], "change_type": "refactor"},
            persist=False,
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"
        assert "persist=true" in result["error"]["message"]

    def test_harness_status_rejects_invalid_run_id(self, mcp_project_root: Path):
        from codegraph.mcp_server import codegraph_harness_status

        result = codegraph_harness_status("..\\bad")

        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"

    def test_harness_artifacts_lists_without_content(self, mcp_project_root: Path):
        from codegraph.mcp_server import codegraph_harness_artifacts, codegraph_harness_run

        run_result = codegraph_harness_run(
            "workflow.impact",
            input={"files": ["greeter.py"], "change_type": "refactor"},
        )
        run_id = run_result["data"]["run_id"]

        result = codegraph_harness_artifacts(run_id)

        assert result["ok"] is True
        artifacts = result["data"]["artifacts"]
        assert any(item["name"] == "report.md" for item in artifacts)
        assert all("content" not in item for item in artifacts)

    def test_harness_artifacts_reads_small_content_when_requested(
        self,
        mcp_project_root: Path,
    ):
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
        artifact = result["data"]["artifact"]
        assert artifact["name"] == "report.md"
        assert isinstance(artifact["content"], str)
        assert len(artifact["content"]) > 0

    def test_harness_artifacts_rejects_escape_name(self, mcp_project_root: Path):
        from codegraph.mcp_server import codegraph_harness_artifacts, codegraph_harness_run

        run_result = codegraph_harness_run(
            "workflow.impact",
            input={"files": ["greeter.py"], "change_type": "refactor"},
        )
        run_id = run_result["data"]["run_id"]

        result = codegraph_harness_artifacts(
            run_id,
            artifact_name="..\\report.md",
            include_content=True,
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"

    def test_harness_artifacts_rejects_large_content(
        self,
        mcp_project_root: Path,
    ):
        from codegraph.mcp_server import codegraph_harness_artifacts

        store = RunStore(project_root=mcp_project_root)
        state = store.create_run(
            module_id="workflow.impact",
            input_params={"files": ["greeter.py"], "change_type": "refactor"},
            project_root=str(mcp_project_root),
        )
        manager = ArtifactManager(store.artifacts_dir(state.run_id))
        manager.write_text_artifact("big.txt", "x" * (33 * 1024))

        result = codegraph_harness_artifacts(
            state.run_id,
            artifact_name="big.txt",
            include_content=True,
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "ARTIFACT_TOO_LARGE"

    def test_harness_artifacts_requires_name_for_content(self, mcp_project_root: Path):
        from codegraph.mcp_server import codegraph_harness_artifacts, codegraph_harness_run

        run_result = codegraph_harness_run(
            "workflow.impact",
            input={"files": ["greeter.py"], "change_type": "refactor"},
        )
        run_id = run_result["data"]["run_id"]

        result = codegraph_harness_artifacts(run_id, include_content=True)

        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"
