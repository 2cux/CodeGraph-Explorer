"""Reusable presentation helpers for the workflow find command/module."""

from __future__ import annotations

import json
from typing import Any


def build_workflow_find_result(
    *,
    input_data: dict[str, Any],
    results: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    reason: str,
    confidence: str,
    warnings: list[dict[str, Any]],
    total: int,
    next_required_steps: list[str],
) -> dict[str, Any]:
    """Normalize workflow find output for harness and CLI consumers."""
    return {
        "ok": True,
        "workflow": "find",
        "input": {
            "query": str(input_data.get("query", "")).strip(),
            "types": list(input_data.get("types", []) or []),
            "paths": list(input_data.get("paths", []) or []),
            "limit": int(input_data.get("limit", 10) or 10),
            "include_details": bool(input_data.get("include_details", True)),
            "include_snippets": bool(input_data.get("include_snippets", False)),
            "include_tests": bool(input_data.get("include_tests", True)),
            "format": str(input_data.get("format", "markdown") or "markdown"),
        },
        "results": results,
        "candidates": candidates,
        "reason": reason,
        "confidence": confidence,
        "total": total,
        "next_required_steps": next_required_steps,
        "warnings": warnings,
        "artifacts": {
            "markdown_report": "artifacts/report.md",
            "json_report": "artifacts/report.json",
        },
    }


def build_workflow_find_cli_json(result: dict[str, Any]) -> str:
    """Format workflow find output for the legacy CLI JSON surface."""
    return json.dumps(result, indent=2, ensure_ascii=False)


def build_workflow_find_markdown(result: dict[str, Any]) -> str:
    """Format workflow find output for Markdown surfaces."""
    input_data = result.get("input", {})
    warnings = result.get("warnings", [])
    results = result.get("results", [])
    candidates = result.get("candidates", [])

    lines: list[str] = []
    lines.append("# CodeGraph Find Workflow Report")
    lines.append("")

    lines.append("## Input")
    lines.append(f"- Query: `{input_data.get('query', '')}`")
    types = input_data.get("types", []) or []
    paths = input_data.get("paths", []) or []
    lines.append(f"- Types: {', '.join(types) if types else '(all)'}")
    lines.append(f"- Paths: {', '.join(paths) if paths else '(all)'}")
    lines.append(f"- Limit: {input_data.get('limit', 10)}")
    lines.append(
        f"- Include details: {str(bool(input_data.get('include_details', True))).lower()}"
    )
    lines.append(
        f"- Include snippets: {str(bool(input_data.get('include_snippets', False))).lower()}"
    )
    lines.append(
        f"- Include tests: {str(bool(input_data.get('include_tests', True))).lower()}"
    )
    lines.append("")

    lines.append("## Summary")
    lines.append(f"- Results: {result.get('total', len(results))}")
    lines.append(f"- Confidence: {result.get('confidence', 'unknown')}")
    lines.append(f"- Reason: {result.get('reason', '')}")
    lines.append("")

    lines.append("## Results")
    if results:
        for index, item in enumerate(results, 1):
            lines.append(
                f"{index}. `{item.get('symbol', '?')}`"
                f" [{item.get('type', '?')}]"
                f" in `{item.get('file', '?')}`"
            )
            location = _format_location(item.get("line_start"), item.get("line_end"))
            if location:
                lines.append(f"   - Location: {location}")
            score = item.get("score")
            if score is not None:
                lines.append(f"   - Score: {score:.2f}")
            match_sources = item.get("match_sources", []) or []
            if match_sources:
                lines.append(f"   - Match sources: {', '.join(match_sources)}")
            item_reason = item.get("reason")
            if item_reason:
                lines.append(f"   - Reason: {item_reason}")
            details = item.get("details")
            if isinstance(details, dict):
                signature = details.get("signature")
                if signature:
                    lines.append(f"   - Signature: `{signature}`")
                framework = details.get("framework")
                if framework:
                    lines.append(f"   - Framework: {framework}")
                tags = details.get("tags", []) or []
                if tags:
                    lines.append(f"   - Tags: {', '.join(tags)}")
                doc = details.get("doc")
                if doc:
                    lines.append(f"   - Doc: {doc}")
            snippet = item.get("snippet")
            if isinstance(snippet, dict) and snippet.get("snippet"):
                lines.append("   - Snippet:")
                lines.append("")
                lines.append("```")
                lines.append(str(snippet.get("snippet", "")).rstrip())
                lines.append("```")
        lines.append("")
    else:
        lines.append("*(no results found)*")
        lines.append("")

    lines.append("## Candidates")
    if candidates:
        for candidate in candidates:
            candidate_name = candidate.get("symbol") or candidate.get("name") or "?"
            candidate_file = candidate.get("file") or candidate.get("file_path") or "?"
            candidate_type = candidate.get("type", "?")
            lines.append(f"- `{candidate_name}` [{candidate_type}] in `{candidate_file}`")
    else:
        lines.append("*(none)*")
    lines.append("")

    lines.append("## Required next step")
    for step in result.get("next_required_steps", []) or []:
        lines.append(f"- {step}")
    lines.append("")

    if warnings:
        lines.append("## Warnings")
        for warning in warnings:
            if isinstance(warning, dict):
                lines.append(f"- {warning.get('message', str(warning))}")
            else:
                lines.append(f"- {warning}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "*Generated by CodeGraph workflow find. "
        "Deterministic indexed search with follow-through guidance.*"
    )
    lines.append("")
    return "\n".join(lines)


def _format_location(line_start: Any, line_end: Any) -> str:
    """Render a source location range."""
    if not line_start:
        return ""
    location = f"L{line_start}"
    if line_end and line_end != line_start:
        location += f"-{line_end}"
    return location
