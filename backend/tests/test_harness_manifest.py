from __future__ import annotations

from pathlib import Path

from codegraph.harness.bootstrap import register_builtin_modules
from codegraph.harness.manifest import list_builtin_manifests, manifest_for
from codegraph.harness.registry import get_module, list_modules
from codegraph.harness.runner import HarnessRunner


def test_builtin_manifest_ids_and_reserved_flags() -> None:
    manifests = {manifest.id: manifest for manifest in list_builtin_manifests()}

    assert sorted(manifests) == [
        "agent_ab.regression",
        "benchmark.gate",
        "doctor.run",
        "enrich.import",
        "enrich.prepare",
        "enrich.validate",
        "mcp.execute",
        "workflow.explain",
        "workflow.find",
        "workflow.impact",
        "workflow.test_audit",
    ]
    assert manifests["workflow.impact"].is_stable is True
    assert manifests["doctor.run"].is_stable is True
    assert manifests["enrich.prepare"].is_stable is False
    assert "reserved" in manifests["enrich.prepare"].description.lower()
    assert "planned" in manifests["mcp.execute"].description.lower()


def test_builtin_modules_are_registered(monkeypatch) -> None:
    monkeypatch.setattr("codegraph.harness.registry._MODULES", {}, raising=False)

    register_builtin_modules()

    manifests = list_modules()
    assert [manifest.id for manifest in manifests] == [
        "agent_ab.regression",
        "benchmark.gate",
        "doctor.run",
        "enrich.import",
        "enrich.prepare",
        "enrich.validate",
        "mcp.execute",
        "workflow.explain",
        "workflow.find",
        "workflow.impact",
        "workflow.test_audit",
    ]
    assert get_module("doctor.run") is not None


def test_reserved_module_runs_with_reserved_payload(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("codegraph.harness.registry._MODULES", {}, raising=False)
    register_builtin_modules()

    result = HarnessRunner().run(
        "enrich.prepare",
        {},
        project_root=tmp_path,
        run_id="reserved-module-run",
    )

    assert result.status.value == "succeeded"
    assert result.output == {
        "ok": False,
        "status": "reserved",
        "message": "This module is reserved for a later implementation.",
    }


def test_doctor_run_manifest_is_stable() -> None:
    manifest = manifest_for("doctor.run")
    assert manifest.is_stable is True
    assert manifest.category == "doctor"
