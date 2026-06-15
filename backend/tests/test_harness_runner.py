from __future__ import annotations

import json
from pathlib import Path

from codegraph.harness.models import HarnessModuleManifest, RunStatus
from codegraph.harness.registry import get_module, list_modules, register_module
from codegraph.harness.runner import HarnessRunner
from codegraph.harness.store import RunStore


class _SuccessModule:
    manifest = HarnessModuleManifest(
        id="test.success",
        name="Test Success",
        description="Harness test module",
        category="workflow",
    )

    def run(self, ctx, input_data: dict[str, object]) -> dict[str, object]:
        ctx.log_info("module started")
        ctx.log_warning("warning message")
        ctx.event("custom.progress", {"step": "halfway"})
        ctx.checkpoint("halfway", {"count": 1})
        ctx.artifact_text("report.md", "# ok\n")
        ctx.artifact_json("report.json", {"ok": True})
        return {"echo": input_data, "ok": True}


class _FailureError(RuntimeError):
    def __init__(self, message: str, partial_output: dict[str, object]) -> None:
        super().__init__(message)
        self.partial_output = partial_output


class _FailureModule:
    manifest = HarnessModuleManifest(
        id="test.failure",
        name="Test Failure",
        description="Harness failure module",
        category="workflow",
    )

    def run(self, ctx, input_data: dict[str, object]) -> dict[str, object]:
        ctx.log_info("before failure")
        raise _FailureError("boom", {"before": input_data})


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_register_and_list_modules(monkeypatch) -> None:
    monkeypatch.setattr("codegraph.harness.registry._MODULES", {}, raising=False)

    register_module(_SuccessModule())

    assert get_module("test.success") is not None
    assert [manifest.id for manifest in list_modules()] == ["test.success"]


def test_harness_runner_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("codegraph.harness.registry._MODULES", {}, raising=False)
    register_module(_SuccessModule())

    runner = HarnessRunner()
    result = runner.run(
        "test.success",
        {"value": 42},
        project_root=tmp_path,
        run_id="test-success-run",
    )

    run_dir = tmp_path / ".codegraph" / "runs" / "test-success-run"

    assert result.status == RunStatus.SUCCEEDED
    assert result.output == {"echo": {"value": 42}, "ok": True}
    assert sorted(result.artifacts) == ["report.json", "report.md"]

    state = _load_json(run_dir / "state.json")
    assert state["status"] == "succeeded"
    assert state["output_path"] == "output.json"

    manifest = _load_json(run_dir / "manifest.json")
    assert manifest["id"] == "test.success"

    output = _load_json(run_dir / "output.json")
    assert output["ok"] is True

    event_types = [
        json.loads(line)["type"]
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert event_types == [
        "run.created",
        "module.started",
        "custom.progress",
        "checkpoint.recorded",
        "artifact.written",
        "artifact.written",
        "module.finished",
    ]

    stdout_log = (run_dir / "logs" / "stdout.log").read_text(encoding="utf-8")
    stderr_log = (run_dir / "logs" / "stderr.log").read_text(encoding="utf-8")
    assert "INFO module started" in stdout_log
    assert "WARNING warning message" in stderr_log
    assert (run_dir / "checkpoints.jsonl").exists()


def test_harness_runner_failure_writes_error_and_partial_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("codegraph.harness.registry._MODULES", {}, raising=False)
    register_module(_FailureModule())

    runner = HarnessRunner()
    result = runner.run(
        "test.failure",
        {"value": 7},
        project_root=tmp_path,
        run_id="test-failure-run",
    )

    run_dir = tmp_path / ".codegraph" / "runs" / "test-failure-run"

    assert result.status == RunStatus.FAILED
    assert result.output == {"before": {"value": 7}}
    assert "boom" in (result.error or "")
    assert result.error == "_FailureError: boom"
    assert result.error_details is not None
    assert result.error_details["message"] == "boom"
    assert "Traceback" in result.error_details["traceback"]

    state = _load_json(run_dir / "state.json")
    assert state["status"] == "failed"
    assert "boom" in state["error"]

    output = _load_json(run_dir / "output.json")
    assert output == {"before": {"value": 7}}

    event_types = [
        json.loads(line)["type"]
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert event_types[-1] == "module.failed"

    stderr_log = (run_dir / "logs" / "stderr.log").read_text(encoding="utf-8")
    assert "ERROR boom" in stderr_log


def test_harness_runner_non_persistent_cleanup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("codegraph.harness.registry._MODULES", {}, raising=False)
    register_module(_SuccessModule())

    runner = HarnessRunner()
    result = runner.run(
        "test.success",
        {"value": 1},
        project_root=tmp_path,
        persist=False,
        run_id="test-ephemeral-run",
    )

    assert result.status == RunStatus.SUCCEEDED
    assert not (tmp_path / ".codegraph" / "runs" / "test-ephemeral-run").exists()


def test_harness_runner_uses_injected_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("codegraph.harness.registry._MODULES", {}, raising=False)
    register_module(_SuccessModule())

    store = RunStore(project_root=tmp_path)
    result = HarnessRunner(store=store).run(
        "test.success",
        {"value": 3},
        project_root=tmp_path,
        run_id="test-injected-store-run",
    )

    assert result.status == RunStatus.SUCCEEDED
    assert (store.base_dir / "test-injected-store-run" / "state.json").exists()
