"""Harness module for ``workflow.impact``."""

from __future__ import annotations

from typing import Any

from codegraph.harness.manifest import manifest_for
from codegraph.harness.module_utils import coerce_str_list, load_graph_store
from codegraph.indexer.status import get_index_status
from codegraph.workflow import run_pre_edit_check
from codegraph.workflow_impact_presenter import (
    build_workflow_impact_markdown,
)


def run_workflow_impact(project_root, input_data: dict[str, Any]) -> dict[str, Any]:
    """Run the existing pre-edit helper and normalize harness output."""
    files = coerce_str_list(input_data.get("files"))
    symbols = coerce_str_list(input_data.get("symbols"))
    store, cg_dir = load_graph_store(project_root)
    project_root_str = str(cg_dir.parent)
    helper_result = run_pre_edit_check(
        store=store,
        files=files,
        symbols=symbols,
        change_type=str(input_data.get("change_type", "unknown")),
        description=input_data.get("description"),
        include_tests=bool(input_data.get("include_tests", True)),
        limit=int(input_data.get("limit", 50)),
    )
    index_status = get_index_status(project_root_str)
    impact_summary = helper_result.get("impact_summary", {})
    return {
        "ok": True,
        "workflow": "impact",
        "input": {
            "files": files,
            "symbols": symbols,
            "change_type": str(input_data.get("change_type", "unknown")),
        },
        "change_type": str(input_data.get("change_type", "unknown")),
        "description": helper_result.get("description", ""),
        "index_status": {
            "status": index_status.get("status", "unknown"),
            "project_root": index_status.get("project_root", project_root_str),
            "index_path": str(index_status.get("index_path") or ""),
            "indexed_at": index_status.get("indexed_at"),
            "stats": index_status.get("stats", {}) or {},
            "warnings": index_status.get("warnings", []) or [],
            "last_change_summary": index_status.get("last_change_summary", {}) or {},
            "suggested_fix": index_status.get("suggested_fix"),
            "last_error": index_status.get("last_error"),
        },
        "risk_level": impact_summary.get("risk_level", "unknown"),
        "planned_files": helper_result.get("planned_files", []),
        "planned_symbols": helper_result.get("planned_symbols", []),
        "impact_summary": impact_summary,
        "affected_callers": helper_result.get("affected_callers", []),
        "affected_files": helper_result.get("affected_files", []),
        "affected_tests": helper_result.get("affected_tests", []),
        "recommended_checks": helper_result.get("recommended_checks", []),
        "impact_errors": helper_result.get("impact_errors", []),
        "warnings": helper_result.get("warnings", []),
        "artifacts": {
            "markdown_report": "artifacts/report.md",
            "json_report": "artifacts/report.json",
        },
    }


class WorkflowImpactModule:
    """Run the stable impact workflow through the harness runner."""

    manifest = manifest_for("workflow.impact")

    def run(self, ctx, input_data: dict[str, Any]) -> dict[str, Any]:
        files = coerce_str_list(input_data.get("files"))
        symbols = coerce_str_list(input_data.get("symbols"))
        ctx.log_info("loading graph store for workflow.impact")
        ctx.checkpoint(
            "inputs.normalized",
            {"files": files, "symbols": symbols, "project_root": str(ctx.project_root)},
        )
        result = run_workflow_impact(ctx.project_root, input_data)
        ctx.checkpoint(
            "workflow.impact.completed",
            {
                "risk_level": result.get("risk_level", "unknown"),
                "planned_symbols": len(result.get("planned_symbols", [])),
                "affected_files": len(result.get("affected_files", [])),
                "affected_tests": len(result.get("affected_tests", [])),
            },
        )
        ctx.artifact_json("report.json", result)
        ctx.artifact_text("report.md", build_workflow_impact_markdown(result))
        return result
