"""Harness module for ``workflow.explain``."""

from __future__ import annotations

from typing import Any

from codegraph.harness.manifest import manifest_for
from codegraph.harness.module_utils import json_report, load_graph_store
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
            include_snippet=bool(input_data.get("include_snippet", True)),
            include_tests=bool(input_data.get("include_tests", True)),
            include_relationships=bool(input_data.get("include_relationships", True)),
            max_snippet_lines=int(input_data.get("max_snippet_lines", 40)),
            project_root=str(ctx.project_root),
        )
        ctx.artifact_json("report.json", result)
        ctx.artifact_text("report.md", json_report("Workflow Explain", result))
        return result
