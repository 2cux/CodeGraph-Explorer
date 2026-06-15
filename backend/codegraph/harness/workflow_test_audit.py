"""Harness module for ``workflow.test_audit``."""

from __future__ import annotations

from typing import Any

from codegraph.harness.manifest import manifest_for
from codegraph.harness.module_utils import coerce_str_list, json_report, load_graph_store
from codegraph.workflow import run_test_audit


class WorkflowTestAuditModule:
    """Run the stable test-audit workflow through the harness runner."""

    manifest = manifest_for("workflow.test_audit")

    def run(self, ctx, input_data: dict[str, Any]) -> dict[str, Any]:
        paths = coerce_str_list(input_data.get("paths")) or None
        types = coerce_str_list(input_data.get("types")) or None
        ctx.log_info("loading graph store for workflow.test_audit")
        store, _cg_dir = load_graph_store(ctx.project_root)
        ctx.checkpoint(
            "inputs.normalized",
            {"paths": paths or [], "types": types or [], "project_root": str(ctx.project_root)},
        )
        result = run_test_audit(
            store=store,
            paths=paths,
            types=types,
            include_low_confidence=bool(input_data.get("include_low_confidence", True)),
            limit=int(input_data.get("limit", 50)),
            project_root=str(ctx.project_root),
        )
        ctx.artifact_json("report.json", result)
        ctx.artifact_text("report.md", json_report("Workflow Test Audit", result))
        return result
