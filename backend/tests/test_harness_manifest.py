from __future__ import annotations

from pathlib import Path

from codegraph.harness.docs import DocsGenerator
from codegraph.harness.bootstrap import register_builtin_modules
from codegraph.harness.manifest import list_builtin_manifests, manifest_for
from codegraph.harness.module_utils import coerce_bool
from codegraph.harness.registry import (
    get_module,
    list_modules,
    register_module,
    reset_builtin_modules_registered,
)
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
    assert manifests["workflow.impact"].input_schema is not None
    assert manifests["workflow.impact"].output_schema is not None
    assert manifests["workflow.impact"].default_artifacts == ["report.md", "report.json"]
    assert manifests["enrich.prepare"].default_artifacts == []
    assert "reserved" in manifests["enrich.prepare"].description.lower()
    assert "planned" in manifests["mcp.execute"].description.lower()


def test_builtin_modules_are_registered(monkeypatch) -> None:
    monkeypatch.setattr("codegraph.harness.registry._MODULES", {}, raising=False)
    reset_builtin_modules_registered()

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
    reset_builtin_modules_registered()
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


def test_workflow_explain_schema_requires_exactly_one_target() -> None:
    manifest = manifest_for("workflow.explain")
    one_of = manifest.input_schema["oneOf"]  # type: ignore[index]
    assert one_of == [
        {"required": ["symbol"], "not": {"required": ["file"]}},
        {"required": ["file"], "not": {"required": ["symbol"]}},
    ]


def test_docs_generator_uses_builtin_manifests_not_runtime_registry(monkeypatch) -> None:
    class _InjectedModule:
        manifest = {
            "id": "test.injected",
            "name": "Injected",
            "description": "runtime only",
            "category": "workflow",
        }

    monkeypatch.setattr("codegraph.harness.registry._MODULES", {}, raising=False)
    reset_builtin_modules_registered()
    register_module(_InjectedModule())

    content = DocsGenerator().render()

    assert "test.injected" not in content
    assert "workflow.impact" in content


def test_registry_lazily_registers_builtin_modules(monkeypatch) -> None:
    monkeypatch.setattr("codegraph.harness.registry._MODULES", {}, raising=False)
    reset_builtin_modules_registered()

    module = get_module("doctor.run")

    assert module is not None
    assert module.manifest.id == "doctor.run"


def test_coerce_bool_parses_string_false() -> None:
    assert coerce_bool("false", default=True) is False
    assert coerce_bool("0", default=True) is False
    assert coerce_bool("true", default=False) is True
