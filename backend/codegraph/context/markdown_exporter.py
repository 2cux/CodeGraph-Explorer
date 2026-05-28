"""Markdown export for Context Pack — human-readable output.

PRD §15 — Markdown export format.
"""

from pathlib import Path

from codegraph.context.models import ContextPack


def export_to_markdown(pack: ContextPack) -> str:
    """Render a ContextPack as a formatted Markdown string."""
    lines: list[str] = []
    _w = lines.append  # local alias for speed

    # ── Header ─────────────────────────────────────────────────────────────
    _w("# CodeGraph Context Pack")
    _w("")
    _w(f"- **Pack ID:** `{pack.pack_id or 'N/A'}`")
    _w(f"- **Schema Version:** {pack.schema_version}")
    if pack.repo.get("name"):
        _w(f"- **Repository:** {pack.repo['name']}")
    _w("")

    # ── Task ───────────────────────────────────────────────────────────────
    _w("## Task")
    _w("")
    _w(pack.task.raw_request or "_No task description provided._")
    _w("")
    if pack.task.intent:
        _w(f"- **Intent:** `{pack.task.intent.value}`")
    if pack.task.keywords:
        _w(f"- **Keywords:** {', '.join(pack.task.keywords)}")
    if pack.task.target_symbols:
        _w(f"- **Target Symbols:** {', '.join(pack.task.target_symbols)}")
    _w("")

    # ── Entry Points ───────────────────────────────────────────────────────
    _w("## Entry Points")
    _w("")
    if pack.entry_points:
        for ep in pack.entry_points:
            _w(f"- `{ep.symbol_id}`")
            _w(f"  - **Type:** {ep.type}")
            _w(f"  - **File:** {ep.file_path}")
            if ep.reason:
                _w(f"  - **Reason:** {ep.reason}")
            _w(f"  - **Score:** {ep.score:.2f}")
            if ep.match_sources:
                _w(f"  - **Match:** {', '.join(ep.match_sources)}")
            _w("")
    else:
        _w("_No entry points found._")
        _w("")

    # ── Related Tests (existing) ───────────────────────────────────────────
    _w("## Related Tests")
    _w("")
    if pack.related_tests:
        for rt in pack.related_tests:
            _w(f"- `{rt.test_file}` :: `{rt.test_name}` — {rt.reason}")
    else:
        _w("_No existing tests found related to this task._")
    _w("")

    # ── Suggested Tests ────────────────────────────────────────────────────
    if pack.suggested_tests:
        _w("### Suggested Tests")
        _w("")
        for st in pack.suggested_tests:
            _w(f"- `{st.test_name}` in `{st.test_file}` — {st.reason}")
        _w("")

    # ── Recommendations / Reading Order ────────────────────────────────────
    if pack.reading_plan:
        _w("## Recommended Reading Order")
        _w("")
        for step in pack.reading_plan:
            _w(f"{step.step}. `{step.target}` — {step.reason}")
        _w("")

    # ── Call Graph Summary ─────────────────────────────────────────────────
    if pack.call_graph.nodes:
        _w("## Call Graph")
        _w("")
        _w(f"- **Center:** `{pack.call_graph.center}`")
        _w(f"- **Depth:** {pack.call_graph.depth}")
        _w(f"- **Nodes:** {len(pack.call_graph.nodes)}")
        _w(f"- **Edges:** {len(pack.call_graph.edges)}")
        _w("")
        if pack.call_graph.edges:
            _w("### Key Call Relationships")
            _w("")
            for edge in pack.call_graph.edges:
                parts = [f"confidence={edge.confidence:.2f}"]
                if edge.resolution:
                    parts.append(f"resolution={edge.resolution}")
                meta = ", ".join(parts)
                marker = " [low confidence]" if edge.confidence < 0.6 else ""
                _w(f"- `{edge.source}` → `{edge.target}` [{edge.type}, {meta}]{marker}")
            _w("")

    # ── Impact Summary ─────────────────────────────────────────────────────
    if pack.impact.changed_symbol:
        _w("## Impact Summary")
        _w("")
        risk = pack.impact.risk
        _w(f"- **Risk Level:** `{risk.level.value if hasattr(risk.level, 'value') else risk.level}`")
        for reason in risk.reasons:
            _w(f"  - {reason}")
        _w("")

        if pack.impact.affected_files:
            _w("### Affected Files")
            _w("")
            for f in pack.impact.affected_files:
                marker = "!!" if f.priority == "high" else " -"
                _w(f"- {marker} `{f.file_path}` [{f.priority}] — {f.reason}")
            _w("")

        if pack.impact.affected_symbols:
            _w("### Affected Symbols")
            _w("")
            for sym in pack.impact.affected_symbols:
                _w(f"- `{sym.symbol_id}` ({sym.impact_type.value if hasattr(sym.impact_type, 'value') else sym.impact_type}, distance: {sym.distance}) — {sym.reason}")
            _w("")

    # ── Related Symbols ────────────────────────────────────────────────────
    if pack.related_symbols:
        _w("## Related Symbols")
        _w("")
        for rs in pack.related_symbols:
            conf = f" (confidence: {rs.confidence:.2f})"
            _w(f"- `{rs.symbol_id}` — {rs.reason}{conf}")
        _w("")

    # ── Recommended Context Detail ─────────────────────────────────────────
    if pack.recommended_context:
        _w("## Relevant Code")
        _w("")
        for ctx in pack.recommended_context:
            _w(f"### {ctx.symbol_id or ctx.context_id}")
            _w("")
            if ctx.file_path:
                loc = ""
                if ctx.line_start:
                    loc = f" Lines {ctx.line_start}"
                    if ctx.line_end and ctx.line_end != ctx.line_start:
                        loc += f"-{ctx.line_end}"
                    loc = f" ({ctx.file_path}{loc})"
                else:
                    loc = f" ({ctx.file_path})"
                _w(f"- **Location:** {loc}")
            _w(f"- **Priority:** {ctx.priority}")
            _w(f"- **Estimated Tokens:** {ctx.estimated_tokens}")
            if ctx.reason:
                _w(f"- **Reason:** {ctx.reason}")
            _w("")
            if ctx.content:
                _w("```python")
                _w(ctx.content)
                _w("```")
                _w("")
            elif ctx.type == "file_summary":
                _w(f"_Summary reference — see file for details._")
                _w("")
            elif ctx.type == "call_chain":
                _w(f"_Call chain reference — see call graph above._")
                _w("")

    # ── Agent Instructions ─────────────────────────────────────────────────
    _w("## Agent Instructions")
    _w("")
    instructions = pack.agent_instructions
    if instructions.summary:
        _w(f"**Summary:** {instructions.summary}")
        _w("")
    if instructions.recommended_strategy:
        _w("### Recommended Strategy")
        _w("")
        for s in instructions.recommended_strategy:
            _w(f"- {s}")
        _w("")
    if instructions.warnings:
        _w("### Warnings")
        _w("")
        for w in instructions.warnings:
            _w(f"- [Warning] {w}")
        _w("")

    # ── Footer ─────────────────────────────────────────────────────────────
    if pack.exports.markdown_path or pack.exports.json_path:
        _w("---")
        _w("")
        _w("### Exported Files")
        _w("")
        if pack.exports.markdown_path:
            _w(f"- Markdown: `{pack.exports.markdown_path}`")
        if pack.exports.json_path:
            _w(f"- JSON: `{pack.exports.json_path}`")

    return "\n".join(lines)


def save_markdown(pack: ContextPack, output_path: str) -> None:
    """Write the Markdown export to a file."""
    content = export_to_markdown(pack)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
