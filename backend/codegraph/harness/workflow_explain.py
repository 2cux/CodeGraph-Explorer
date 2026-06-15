"""Harness module for ``workflow.explain``."""

from __future__ import annotations

from typing import Any

from codegraph.harness.manifest import manifest_for
from codegraph.harness.module_utils import coerce_bool, json_report, load_graph_store
from codegraph.workflow import run_explain


class WorkflowExplainModule:
    """Run the stable explain workflow through the harness runner."""

    manifest = manifest_for("workflow.explain")

    def run(self, ctx, input_data: dict[str, Any]) -> dict[str, Any]:
        ctx.log_info("loading graph store for workflow.explain")
        store, _cg_dir = load_graph_store(ctx.project_root)
        ctx.checkpoint(
            "inputs.normalized",
            {
                "symbol": input_data.get("symbol"),
                "file": input_data.get("file"),
                "project_root": str(ctx.project_root),
            },
        )
        result = run_explain(
            store=store,
            symbol=input_data.get("symbol"),
            file=input_data.get("file"),
            include_snippet=coerce_bool(input_data.get("include_snippet"), default=True),
            include_tests=coerce_bool(input_data.get("include_tests"), default=True),
            include_relationships=coerce_bool(
                input_data.get("include_relationships"),
                default=True,
            ),
            max_snippet_lines=int(input_data.get("max_snippet_lines", 40)),
            project_root=str(ctx.project_root),
        )
        ctx.artifact_json("report.json", result)
        ctx.artifact_text("report.md", json_report("Workflow Explain", result))
        return result
