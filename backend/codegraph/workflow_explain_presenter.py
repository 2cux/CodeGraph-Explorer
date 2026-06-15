"""Reusable presentation helpers for the workflow explain command/module."""

from __future__ import annotations

import json
from typing import Any


def build_workflow_explain_result(
    *,
    input_data: dict[str, Any],
    explain_result: dict[str, Any],
    relationships: dict[str, Any],
) -> dict[str, Any]:
    """Normalize workflow explain output for harness and CLI consumers."""
    target = dict(explain_result.get("target", {}))
    warnings = list(explain_result.get("warnings", []))
    test_signal = dict(explain_result.get("test_signal", {}))
    source_snippet = dict(explain_result.get("source_snippet", {}))
    target_kind = str(target.get("kind", explain_result.get("target_kind", "unknown")))

    if target_kind == "symbol":
        explanation = dict(explain_result.get("explanation", {}))
        summary = str(explanation.get("summary", "")).strip()
        confidence = str(explanation.get("confidence", "unknown"))
        evidence = list(explain_result.get("evidence", []))
    else:
        likely_role = str(explain_result.get("likely_role", "unknown"))
        symbol_count = int(explain_result.get("symbol_count", 0) or 0)
        primary_symbols = list(explain_result.get("primary_symbols", []))
        summary = _build_file_summary(likely_role, symbol_count)
        confidence = str(explain_result.get("likely_role_confidence", "unknown"))
        evidence = _build_file_evidence(
            target=target,
            likely_role=likely_role,
            primary_symbols=primary_symbols,
            implementation_signals=explain_result.get("implementation_signals", {}),
        )

    result: dict[str, Any] = {
        "ok": True,
        "workflow": "explain",
        "input": {
            "symbol": input_data.get("symbol"),
            "file": input_data.get("file"),
            "include_neighbors": bool(input_data.get("include_neighbors", True)),
            "include_snippets": bool(input_data.get("include_snippets", True)),
            "format": str(input_data.get("format", "markdown")),
        },
        "target": target,
        "summary": summary,
        "confidence": confidence,
        "evidence": evidence,
        "relationships": relationships,
        "test_signal": test_signal,
        "warnings": warnings,
        "artifacts": {
            "markdown_report": "artifacts/report.md",
            "json_report": "artifacts/report.json",
        },
    }
    if source_snippet.get("included"):
        result["source_snippet"] = source_snippet
    return result


def build_workflow_explain_cli_json(result: dict[str, Any]) -> str:
    """Format workflow explain output for the legacy CLI JSON surface."""
    return json.dumps(result, indent=2, ensure_ascii=False)


def build_workflow_explain_markdown(result: dict[str, Any]) -> str:
    """Format workflow explain output for Markdown surfaces."""
    target = result.get("target", {})
    relationships = result.get("relationships", {})
    test_signal = result.get("test_signal", {})
    warnings = result.get("warnings", [])
    evidence = result.get("evidence", [])
    input_data = result.get("input", {})
    source_snippet = result.get("source_snippet", {})

    lines: list[str] = []
    lines.append("# CodeGraph Explain Workflow Report")
    lines.append("")

    lines.append("## Input")
    if input_data.get("symbol"):
        lines.append(f"- Symbol: `{input_data['symbol']}`")
    if input_data.get("file"):
        lines.append(f"- File: `{input_data['file']}`")
    lines.append(f"- Include neighbors: {str(bool(input_data.get('include_neighbors', True))).lower()}")
    lines.append(f"- Include snippets: {str(bool(input_data.get('include_snippets', True))).lower()}")
    lines.append("")

    lines.append("## Target")
    lines.extend(_render_target_lines(target))
    lines.append("")

    lines.append("## Summary")
    lines.append(f"- Summary: {result.get('summary', '')}")
    lines.append(f"- Confidence: {result.get('confidence', 'unknown')}")
    lines.append("")

    lines.append("## Evidence")
    if evidence:
        for item in evidence:
            item_type = item.get("type", "evidence") if isinstance(item, dict) else "evidence"
            reason = item.get("reason", "") if isinstance(item, dict) else str(item)
            lines.append(f"- [{item_type}] {reason}")
    else:
        lines.append("*(none)*")
    lines.append("")

    lines.append("## Relationships")
    lines.append(f"- Callers: {relationships.get('callers_count', 0)}")
    lines.append(f"- Callees: {relationships.get('callees_count', 0)}")
    top_callers = relationships.get("top_callers", []) or []
    top_callees = relationships.get("top_callees", []) or []
    if top_callers:
        lines.append("- Top callers:")
        for item in top_callers[:5]:
            lines.append(_render_relationship_line(item, "caller"))
    if top_callees:
        lines.append("- Top callees:")
        for item in top_callees[:5]:
            lines.append(_render_relationship_line(item, "callee"))
    if not top_callers and not top_callees:
        lines.append("*(none)*")
    lines.append("")

    lines.append("## Test Signal")
    lines.append(f"- Status: {test_signal.get('status', 'unknown')}")
    lines.append(f"- Related tests: {test_signal.get('tested_by_count', 0)}")
    related_tests = test_signal.get("related_tests", []) or []
    for item in related_tests[:5]:
        symbol = item.get("symbol") or item.get("name") or item.get("symbol_id", "?")
        file_path = item.get("file") or item.get("file_path", "?")
        lines.append(f"- `{symbol}` (`{file_path}`)")
    lines.append("")

    if source_snippet.get("included"):
        lines.append("## Source Snippet")
        file_path = source_snippet.get("file") or target.get("file", "?")
        line_start = source_snippet.get("line_start")
        line_end = source_snippet.get("line_end")
        location = ""
        if line_start:
            location = f" L{line_start}"
            if line_end and line_end != line_start:
                location += f"-{line_end}"
        lines.append(f"- File: `{file_path}`{location}")
        lines.append("")
        lines.append("```")
        lines.append(str(source_snippet.get("snippet", "")).rstrip())
        lines.append("```")
        lines.append("")

    if warnings:
        lines.append("## Warnings")
        for warning in warnings:
            message = warning.get("message", str(warning)) if isinstance(warning, dict) else str(warning)
            lines.append(f"- {message}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "*Generated by CodeGraph workflow explain. "
        "Deterministic evidence-backed output with no LLM involvement.*"
    )
    lines.append("")
    return "\n".join(lines)


def _build_file_summary(likely_role: str, symbol_count: int) -> str:
    """Build a deterministic file summary from the explain helper output."""
    role = likely_role if likely_role and likely_role != "unknown" else "unknown role"
    return f"Likely {role}; contains {symbol_count} indexed symbol(s)."


def _build_file_evidence(
    *,
    target: dict[str, Any],
    likely_role: str,
    primary_symbols: list[dict[str, Any]],
    implementation_signals: Any,
) -> list[dict[str, Any]]:
    """Build evidence for file-level explain results."""
    evidence: list[dict[str, Any]] = []
    file_path = target.get("file")
    if file_path:
        evidence.append({
            "type": "file_path",
            "reason": f"Defined in {file_path}.",
        })
    if likely_role and likely_role != "unknown":
        evidence.append({
            "type": "likely_role",
            "reason": likely_role,
        })
    if primary_symbols:
        names = ", ".join(
            str(item.get("name", item.get("symbol_id", "?")))
            for item in primary_symbols[:5]
        )
        evidence.append({
            "type": "primary_symbols",
            "reason": f"Primary indexed symbols: {names}.",
        })
    active_signals = [
        key for key, value in (implementation_signals or {}).items() if value
    ]
    if active_signals:
        evidence.append({
            "type": "implementation_signals",
            "reason": f"Active signals: {', '.join(active_signals[:8])}.",
        })
    return evidence


def _render_target_lines(target: dict[str, Any]) -> list[str]:
    """Render the target block for markdown output."""
    lines = [f"- Kind: {target.get('kind', 'unknown')}"]
    if target.get("symbol"):
        lines.append(f"- Symbol: `{target['symbol']}`")
    if target.get("symbol_id"):
        lines.append(f"- Symbol ID: `{target['symbol_id']}`")
    if target.get("type"):
        lines.append(f"- Type: {target['type']}")
    if target.get("file"):
        lines.append(f"- File: `{target['file']}`")
    line_start = target.get("line_start")
    line_end = target.get("line_end")
    if line_start:
        location = f"L{line_start}"
        if line_end and line_end != line_start:
            location += f"-{line_end}"
        lines.append(f"- Location: {location}")
    return lines


def _render_relationship_line(item: dict[str, Any], role: str) -> str:
    """Render a caller/callee row for markdown output."""
    symbol = item.get("name") or item.get("symbol", item.get("symbol_id", "?"))
    file_path = item.get("file_path") or item.get("file", "?")
    confidence = item.get("confidence", "?")
    return f"  - `{symbol}` (`{file_path}`) [{role}, confidence={confidence}]"
