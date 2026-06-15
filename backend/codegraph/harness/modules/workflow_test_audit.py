"""Harness module for ``workflow.test_audit``."""

from __future__ import annotations

from typing import Any

from codegraph.harness.manifest import manifest_for
from codegraph.harness.module_utils import coerce_bool, coerce_str_list, load_graph_store
from codegraph.workflow import run_test_audit
from codegraph.workflow_test_audit_presenter import (
    build_workflow_test_audit_markdown,
    build_workflow_test_audit_result,
)


class WorkflowTestAuditModule:
    """Run the stable test-audit workflow through the harness runner."""

    manifest = manifest_for("workflow.test_audit")

    def run(self, ctx, input_data: dict[str, Any]) -> dict[str, Any]:
        paths = coerce_str_list(input_data.get("paths"))
        types = coerce_str_list(input_data.get("types"))
        normalized_input = {
            "paths": paths,
            "types": types,
            "include_low_confidence": coerce_bool(
                input_data.get("include_low_confidence"),
                default=True,
            ),
            "limit": int(input_data.get("limit", 50)),
        }
        ctx.log_info("loading graph store for workflow.test_audit")
        store, _cg_dir = load_graph_store(ctx.project_root)
        ctx.checkpoint(
            "inputs.normalized",
            {
                "paths": paths,
                "types": types,
                "project_root": str(ctx.project_root),
            },
        )
        audit_result = run_test_audit(
            store=store,
            paths=paths or None,
            types=types or None,
            include_low_confidence=normalized_input["include_low_confidence"],
            limit=normalized_input["limit"],
            project_root=str(ctx.project_root),
        )
        result = build_workflow_test_audit_result(
            input_data=normalized_input,
            audit_result=audit_result,
        )
        ctx.checkpoint(
            "workflow.test_audit.completed",
            {
                "production_symbols_checked": result["summary"].get(
                    "production_symbols_checked",
                    0,
                ),
                "symbols_without_test_signal": result["summary"].get(
                    "symbols_without_test_signal",
                    0,
                ),
                "warnings": len(result.get("warnings", [])),
            },
        )
        ctx.artifact_json("report.json", result)
        ctx.artifact_text("report.md", build_workflow_test_audit_markdown(result))
        return result
