"""Harness module for ``workflow.impact``."""

from __future__ import annotations

from typing import Any

from codegraph.harness.manifest import manifest_for
from codegraph.harness.module_utils import coerce_str_list, json_report, load_graph_store
from codegraph.workflow import run_pre_edit_check


class WorkflowImpactModule:
    """Run the stable impact workflow through the harness runner."""

    manifest = manifest_for("workflow.impact")

    def run(self, ctx, input_data: dict[str, Any]) -> dict[str, Any]:
        files = coerce_str_list(input_data.get("files"))
        symbols = coerce_str_list(input_data.get("symbols"))
        ctx.log_info("loading graph store for workflow.impact")
        store, _cg_dir = load_graph_store(ctx.project_root)
        ctx.checkpoint(
            "inputs.normalized",
            {"files": files, "symbols": symbols, "project_root": str(ctx.project_root)},
        )
        result = run_pre_edit_check(
            store=store,
            files=files,
            symbols=symbols,
            change_type=str(input_data.get("change_type", "unknown")),
            description=input_data.get("description"),
            include_tests=bool(input_data.get("include_tests", True)),
            limit=int(input_data.get("limit", 50)),
        )
        ctx.artifact_json("report.json", result)
        ctx.artifact_text("report.md", json_report("Workflow Impact", result))
        return result
