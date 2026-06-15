"""Reusable presentation helpers for the workflow impact command/module."""

from __future__ import annotations

import json
from typing import Any


def build_workflow_impact_cli_json(result: dict[str, Any]) -> str:
    """Format workflow impact output for the legacy CLI JSON surface."""
    warnings_list = list(result.get("warnings", []))
    index_status = result.get("index_status", {})
    raw_idx_warnings = index_status.get("warnings", [])
    idx_warnings_list: list[dict[str, Any]] = []
    if isinstance(raw_idx_warnings, list):
        for warning in raw_idx_warnings:
            if isinstance(warning, dict):
                idx_warnings_list.append(warning)
            else:
                idx_warnings_list.append({"message": str(warning)})

    output_data = {
        "ok": bool(result.get("ok", True)),
        "workflow": "impact",
        "input": result.get("input", {}),
        "index_status": {
            "freshness": index_status.get("status", "unknown"),
            "project_root": index_status.get("project_root", ""),
            "index_path": str(index_status.get("index_path") or ""),
            "indexed_at": index_status.get("indexed_at"),
            "stats": index_status.get("stats", {}),
        },
        "planned_symbols": result.get("planned_symbols", []),
        "impact_summary": result.get("impact_summary", {}),
        "affected_callers": result.get("affected_callers", []),
        "affected_files": result.get("affected_files", []),
        "affected_tests": result.get("affected_tests", []),
        "recommended_checks": result.get("recommended_checks", []),
        "warnings": warnings_list + idx_warnings_list,
    }
    return json.dumps(output_data, indent=2, ensure_ascii=False)


def build_workflow_impact_markdown(result: dict[str, Any]) -> str:
    """Format workflow impact output for the legacy CLI Markdown surface."""
    impact_summary = result.get("impact_summary", {})
    planned_symbols = result.get("planned_symbols", [])
    affected_callers = result.get("affected_callers", [])
    affected_files = result.get("affected_files", [])
    affected_tests = result.get("affected_tests", [])
    recommended_checks = result.get("recommended_checks", [])
    warnings_list = result.get("warnings", [])
    change_desc = result.get("description", "")
    input_data = result.get("input", {})
    files = input_data.get("files", []) or []
    symbols = input_data.get("symbols", []) or []
    change_type = input_data.get("change_type", result.get("change_type", "unknown"))
    index_status = result.get("index_status", {})
    fresh = index_status.get("status", "unknown")
    project_root = index_status.get("project_root", "")

    lines: list[str] = []
    lines.append("# CodeGraph Impact Workflow Report")
    lines.append("")

    lines.append("## Input")
    lines.append(f"- Change type: {change_type}")
    if change_desc:
        lines.append(f"- Description: {change_desc}")
    if files:
        lines.append("- Files:")
        for file_path in files:
            lines.append(f"  - `{file_path}`")
    if symbols:
        lines.append("- Symbols:")
        for symbol in symbols:
            lines.append(f"  - `{symbol}`")
    lines.append("")

    lines.append("## Index Status")
    lines.append(f"- Freshness: {fresh}")
    lines.append(f"- Project root: `{project_root}`")
    idx_warnings = index_status.get("warnings", [])
    if isinstance(idx_warnings, list) and idx_warnings:
        for warning in idx_warnings:
            if isinstance(warning, dict):
                lines.append(f"- Warning: {warning.get('message', str(warning))}")
            else:
                lines.append(f"- Warning: {warning}")

    if fresh == "stale":
        lines.append("")
        lines.append(
            "> **Warning: Index is stale.** Results may not reflect recent file changes."
        )
        change_summary = index_status.get("last_change_summary", {})
        total = sum(change_summary.values()) if change_summary else 0
        if total > 0:
            lines.append(f"> {total} file(s) changed since last index.")
        suggested = index_status.get(
            "suggested_fix",
            "Run: codegraph init --incremental",
        )
        lines.append(f"> {suggested}")
    elif fresh == "missing":
        lines.append("")
        lines.append("> **Warning: Index is missing.** Run `codegraph init` first.")
    elif fresh == "indexing":
        lines.append("")
        lines.append(
            "> **Index update is in progress.** Results may reflect the previous index."
        )
    elif fresh == "error":
        lines.append("")
        lines.append(
            f"> **Index error:** {index_status.get('last_error', 'Unknown error')}"
        )

    lines.append("")

    lines.append("## Planned Symbols")
    if planned_symbols:
        lines.append("| Symbol | Type | File | Lines |")
        lines.append("|---|---|---|---|")
        for planned_symbol in planned_symbols[:20]:
            sym_name = planned_symbol.get("symbol", "?")
            sym_type = planned_symbol.get("type", "?")
            sym_file = planned_symbol.get("file", "?")
            line_start = planned_symbol.get("line_start")
            line_end = planned_symbol.get("line_end")
            lines_str = f"L{line_start}" if line_start else ""
            if line_end and line_end != line_start:
                lines_str += f"-{line_end}"
            lines.append(
                f"| `{sym_name}` | {sym_type} | `{sym_file}` | {lines_str} |"
            )
    else:
        lines.append("*(none)*")
    lines.append("")

    lines.append("## Impact Summary")
    lines.append(f"- Risk level: **{impact_summary.get('risk_level', 'unknown')}**")
    lines.append(f"- Confidence: {impact_summary.get('confidence', 'unknown')}")
    lines.append(f"- Summary: {impact_summary.get('summary', '')}")
    lines.append("")

    lines.append("## Affected Callers")
    if affected_callers:
        lines.append("| Symbol | File | Distance | Confidence |")
        lines.append("|---|---|---|---|")
        for caller in affected_callers[:30]:
            caller_name = caller.get("name", caller.get("symbol_id", "?"))
            caller_file = caller.get("file_path", "?")
            caller_dist = caller.get("distance", 0)
            caller_conf = caller.get("confidence", 1.0)
            lines.append(
                f"| `{caller_name}` | `{caller_file}` | {caller_dist} | {caller_conf:.0%} |"
            )
    else:
        lines.append("*(none)*")
    lines.append("")

    lines.append("## Affected Files")
    if affected_files:
        lines.append("| File | Priority | Layer |")
        lines.append("|---|---|---|")
        for affected_file in affected_files[:20]:
            file_path = affected_file.get("file_path", "?")
            priority = affected_file.get("priority", "medium")
            layer = affected_file.get("layer", "unknown")
            lines.append(f"| `{file_path}` | {priority} | {layer} |")
    else:
        lines.append("*(none)*")
    lines.append("")

    lines.append("## Affected Tests")
    if affected_tests:
        lines.append("| Test | File | Confidence |")
        lines.append("|---|---|---|")
        for affected_test in affected_tests[:20]:
            test_name = affected_test.get("name", affected_test.get("symbol_id", "?"))
            test_file = affected_test.get("file_path", "?")
            test_conf = affected_test.get("confidence", 1.0)
            lines.append(f"| `{test_name}` | `{test_file}` | {test_conf:.0%} |")
    else:
        lines.append("*(none)*")
    lines.append("")

    lines.append("## Recommended Checks")
    if recommended_checks:
        for idx, check in enumerate(recommended_checks, 1):
            check_type = check.get("type", "?")
            target = check.get("target", "?")
            reason = check.get("reason", "")
            lines.append(f"{idx}. **[{check_type}]** `{target}`: {reason}")
    else:
        lines.append("*(none)*")
    lines.append("")

    if warnings_list:
        lines.append("## Warnings")
        for warning in warnings_list:
            message = warning.get("message", str(warning))
            lines.append(f"- [!] {message}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "*This is a CodeGraph heuristic impact workflow report. "
        "It does not execute tests or modify files.*"
    )
    lines.append("")
    return "\n".join(lines)
