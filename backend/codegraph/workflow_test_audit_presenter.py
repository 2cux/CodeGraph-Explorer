"""Reusable presentation helpers for the workflow test-audit command/module."""

from __future__ import annotations

import json
from typing import Any


_HEURISTIC_DISCLAIMER = (
    "This is a heuristic graph signal based on CodeGraph tested_by edges. "
    "It is not runtime line coverage."
)


def build_workflow_test_audit_result(
    *,
    input_data: dict[str, Any],
    audit_result: dict[str, Any],
) -> dict[str, Any]:
    """Normalize workflow test-audit output for harness and CLI consumers."""
    summary = dict(audit_result.get("summary", {}))
    symbols_without_tests = list(audit_result.get("symbols_without_tests", []))
    files_without_tests = list(audit_result.get("files_without_tests", []))
    low_confidence_links = list(audit_result.get("low_confidence_links", []))
    warnings = [str(warning) for warning in audit_result.get("warnings", [])]
    path_resolution = dict(audit_result.get("path_resolution", {}))

    return {
        "ok": True,
        "workflow": "test-audit",
        "input": {
            "paths": list(input_data.get("paths", []) or []),
            "types": list(input_data.get("types", []) or []),
            "include_low_confidence": bool(input_data.get("include_low_confidence", True)),
            "limit": int(input_data.get("limit", 50)),
        },
        "coverage_gaps_summary": summary,
        "summary": summary,
        "top_uncovered_production_symbols": symbols_without_tests,
        "symbols_without_tests": symbols_without_tests,
        "files_without_test_signals": files_without_tests,
        "files_without_tests": files_without_tests,
        "low_confidence_links": low_confidence_links,
        "path_resolution": path_resolution,
        "warnings": warnings,
        "heuristic_coverage_disclaimer": _HEURISTIC_DISCLAIMER,
        "artifacts": {
            "markdown_report": "artifacts/report.md",
            "json_report": "artifacts/report.json",
        },
    }


def build_workflow_test_audit_cli_json(result: dict[str, Any]) -> str:
    """Format workflow test-audit output for the legacy CLI JSON surface."""
    output_data = {
        "ok": bool(result.get("ok", True)),
        "workflow": "test-audit",
        "input": result.get("input", {}),
        "coverage_gaps_summary": result.get("coverage_gaps_summary", {}),
        "summary": result.get("summary", {}),
        "top_uncovered_production_symbols": result.get(
            "top_uncovered_production_symbols",
            [],
        ),
        "symbols_without_tests": result.get("symbols_without_tests", []),
        "files_without_test_signals": result.get("files_without_test_signals", []),
        "files_without_tests": result.get("files_without_tests", []),
        "low_confidence_links": result.get("low_confidence_links", []),
        "path_resolution": result.get("path_resolution", {}),
        "warnings": result.get("warnings", []),
        "heuristic_coverage_disclaimer": result.get(
            "heuristic_coverage_disclaimer",
            _HEURISTIC_DISCLAIMER,
        ),
    }
    return json.dumps(output_data, indent=2, ensure_ascii=False)


def build_workflow_test_audit_markdown(result: dict[str, Any]) -> str:
    """Format workflow test-audit output for Markdown surfaces."""
    summary = result.get("coverage_gaps_summary", result.get("summary", {}))
    symbols_without_tests = result.get("top_uncovered_production_symbols", [])
    files_without_tests = result.get("files_without_test_signals", [])
    low_confidence_links = result.get("low_confidence_links", [])
    warnings = result.get("warnings", [])
    input_data = result.get("input", {})
    path_resolution = result.get("path_resolution", {})
    disclaimer = result.get("heuristic_coverage_disclaimer", _HEURISTIC_DISCLAIMER)

    lines: list[str] = []
    lines.append("# CodeGraph Test Audit Report")
    lines.append("")
    lines.append("## Input")
    paths = input_data.get("paths", []) or []
    types = input_data.get("types", []) or []
    if paths:
        lines.append(f"- Requested paths: {', '.join(paths)}")
        lines.append(
            f"- Resolved files in scope: {path_resolution.get('resolved_file_count', 0)}"
        )
    else:
        lines.append("- Scope: all production symbols")
    if types:
        lines.append(f"- Production symbol types: {', '.join(types)}")
    lines.append("")

    lines.append("## Coverage Gaps Summary")
    lines.append(
        f"- Production symbols checked: {summary.get('production_symbols_checked', 0)}"
    )
    lines.append(
        f"- Symbols without test signal: {summary.get('symbols_without_test_signal', 0)}"
    )
    lines.append(
        f"- Files without test signal: {summary.get('files_without_test_signal', 0)}"
    )
    lines.append(f"- Confidence: {summary.get('confidence', 'unknown')}")
    if summary.get("message"):
        lines.append(f"- Summary: {summary.get('message')}")
    lines.append("")

    lines.append("## Top Uncovered Production Symbols")
    if symbols_without_tests:
        lines.append("| Symbol | File | Type | Reason |")
        lines.append("|---|---|---|---|")
        for symbol in symbols_without_tests[:30]:
            lines.append(
                f"| `{symbol.get('symbol', symbol.get('symbol_id', '?'))}` "
                f"| `{symbol.get('file', '?')}` "
                f"| {symbol.get('type', '?')} "
                f"| {symbol.get('reason', '')} |"
            )
    else:
        lines.append("*(none found)*")
    lines.append("")

    lines.append("## Files Without Test Signals")
    if files_without_tests:
        lines.append("| File | Uncovered Symbols | Reason |")
        lines.append("|---|---|---|")
        for item in files_without_tests[:20]:
            lines.append(
                f"| `{item.get('file', '?')}` "
                f"| {item.get('symbols_without_test_signal', 0)} "
                f"| {item.get('reason', '')} |"
            )
    else:
        lines.append("*(none found)*")
    lines.append("")

    if low_confidence_links:
        lines.append("## Low Confidence Test Links")
        lines.append("| Production Symbol | Test Symbol | Confidence |")
        lines.append("|---|---|---|")
        for link in low_confidence_links[:15]:
            lines.append(
                f"| `{link.get('production_symbol', link.get('production_symbol_id', '?'))}` "
                f"| `{link.get('test_symbol', link.get('test_symbol_id', '?'))}` "
                f"| {link.get('confidence', '?')} |"
            )
        lines.append("")

    if warnings:
        lines.append("## Warnings")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    lines.append("## Heuristic Coverage Disclaimer")
    lines.append(disclaimer)
    lines.append("")
    return "\n".join(lines)
