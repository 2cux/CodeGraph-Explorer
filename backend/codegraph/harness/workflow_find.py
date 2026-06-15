"""Harness module for ``workflow.find``."""

from __future__ import annotations

from typing import Any

from codegraph.harness.manifest import manifest_for
from codegraph.harness.module_utils import coerce_str_list, json_report, load_graph_store
from codegraph.workflow import run_find


class WorkflowFindModule:
    """Run the stable find workflow through the harness runner."""

    manifest = manifest_for("workflow.find")

    def run(self, ctx, input_data: dict[str, Any]) -> dict[str, Any]:
        query = str(input_data.get("query", "")).strip()
        if not query:
            raise ValueError("workflow.find requires a non-empty 'query'")
        types = coerce_str_list(input_data.get("types")) or None
        paths = coerce_str_list(input_data.get("paths")) or None
        ctx.log_info("loading graph store for workflow.find")
        store, _cg_dir = load_graph_store(ctx.project_root)
        ctx.checkpoint(
            "inputs.normalized",
            {"query": query, "types": types or [], "paths": paths or []},
        )
        result = run_find(
            store=store,
            query=query,
            types=types,
            paths=paths,
            limit=int(input_data.get("limit", 20)),
            include_tests=bool(input_data.get("include_tests", True)),
        )
        ctx.artifact_json("report.json", result)
        ctx.artifact_text("report.md", json_report("Workflow Find", result))
        return result
