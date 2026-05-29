"""Markdown export for Evidence Pack — human-readable structured evidence.

Section order: Task → Index Status → Entry Point Candidates → Selected
Context → Call Graph → Impact Signals → Tests → Warnings → Pack Notes →
Token Budget.

No Reading Plan, Agent Instructions, or action directives are emitted.
"""

from pathlib import Path

from codegraph.context.models import ContextPack, ContextType


def export_to_markdown(pack: ContextPack) -> str:
    """Render an Evidence Pack as a formatted Markdown string."""
    lines: list[str] = []
    _w = lines.append

    # ── Header ───────────────────────────────────────────────────────
    _w("# CodeGraph Evidence Pack")
    _w("")
    _w(f"- **Pack ID:** `{pack.pack_id or 'N/A'}`")
    _w(f"- **Schema Version:** {pack.schema_version}")
    if pack.created_at:
        _w(f"- **Created:** {pack.created_at}")
    if pack.repo.get("name"):
        _w(f"- **Repository:** {pack.repo['name']}")
    _w("")

    # ── Task ─────────────────────────────────────────────────────────
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

    # ── Index Status ─────────────────────────────────────────────────
    _w("## Index Status")
    _w("")
    ist = pack.index_status
    _w(f"- **Symbols indexed:** {ist.symbol_count}")
    _w(f"- **Edges indexed:** {ist.edge_count}")
    _w(f"- **Format:** {ist.index_format}")
    _w(f"- **Language:** {ist.language}")
    _w("")

    # ── Entry Point Candidates ───────────────────────────────────────
    _w("## Entry Point Candidates")
    _w("")
    _w("_Candidate entry points matched by keyword search. No reading order is implied._")
    _w("")
    if pack.entry_points:
        for ep in pack.entry_points:
            _w(f"- `{ep.symbol_id}`")
            _w(f"  - **Type:** {ep.type}")
            _w(f"  - **File:** {ep.file_path}")
            if ep.reason:
                _w(f"  - **Match reason:** {ep.reason}")
            _w(f"  - **Score:** {ep.score:.2f}")
            if ep.match_sources:
                _w(f"  - **Match sources:** {', '.join(ep.match_sources)}")
            _w("")
    else:
        _w("_No entry point candidates found._")
        _w("")

    # ── Selected Context ─────────────────────────────────────────────
    _w("## Selected Context")
    _w("")
    _w("_Context items selected under token budget. Each item carries its "
       "relation, confidence, and evidence source._")
    _w("")
    if pack.selected_context:
        for ctx in pack.selected_context:
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
            _w(f"- **Priority:** {ctx.priority.value if hasattr(ctx.priority, 'value') else ctx.priority}")
            _w(f"- **Relation:** {ctx.relation}")
            _w(f"- **Content Mode:** {ctx.content_mode.value if hasattr(ctx.content_mode, 'value') else ctx.content_mode}")
            _w(f"- **Confidence:** {ctx.confidence:.2f} ({ctx.confidence_level.value if hasattr(ctx.confidence_level, 'value') else ctx.confidence_level})")
            _w(f"- **Estimated Tokens:** {ctx.estimated_tokens}")
            if ctx.selection_reason:
                _w(f"- **Selection Reason:** {ctx.selection_reason}")
            if ctx.resolution:
                _w(f"- **Resolution:** {ctx.resolution}")
            if ctx.evidence:
                _w(f"- **Evidence:** {ctx.evidence}")
            _w("")
            if ctx.content:
                if ctx.content_mode.value if hasattr(ctx.content_mode, 'value') else ctx.content_mode == "full_source":
                    _w("```python")
                else:
                    _w("```")
                _w(ctx.content)
                _w("```")
                _w("")
    else:
        _w("_No context items selected._")
        _w("")

    # ── Call Graph ───────────────────────────────────────────────────
    if pack.call_graph.nodes:
        _w("## Call Graph")
        _w("")
        _w(f"- **Center:** `{pack.call_graph.center}`")
        _w(f"- **Depth:** {pack.call_graph.depth}")
        _w(f"- **Nodes:** {len(pack.call_graph.nodes)}")
        _w(f"- **Edges:** {len(pack.call_graph.edges)}")
        _w("")
        if pack.call_graph.edges:
            _w("### Call Relationships")
            _w("")
            for edge in pack.call_graph.edges:
                parts = [f"confidence={edge.confidence:.2f}"]
                if edge.resolution:
                    parts.append(f"resolution={edge.resolution}")
                meta = ", ".join(parts)
                marker = " [low confidence]" if edge.confidence < 0.6 else ""
                _w(f"- `{edge.source}` → `{edge.target}` [{edge.type}, {meta}]{marker}")
            _w("")

    # ── Impact Signals ───────────────────────────────────────────────
    if pack.impact.changed_symbol:
        _w("## Impact Signals")
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
                prio = f.priority.value if hasattr(f.priority, 'value') else f.priority
                _w(f"- `{f.file_path}` [{prio}] — {f.reason}")
            _w("")

        if pack.impact.affected_symbols:
            _w("### Affected Symbols")
            _w("")
            for sym in pack.impact.affected_symbols:
                itype = sym.impact_type.value if hasattr(sym.impact_type, 'value') else sym.impact_type
                _w(f"- `{sym.symbol_id}` ({itype}, distance: {sym.distance}, "
                   f"confidence: {sym.confidence:.2f}) — {sym.reason}")
            _w("")

    # ── Related Symbols ──────────────────────────────────────────────
    if pack.related_symbols:
        _w("## Related Symbols")
        _w("")
        for rs in pack.related_symbols:
            rel = rs.relation.value if hasattr(rs.relation, 'value') else rs.relation
            conf = f" (confidence: {rs.confidence:.2f})"
            _w(f"- `{rs.symbol_id}` [{rel}]{conf} — {rs.reason}")
        _w("")

    # ── Tests ────────────────────────────────────────────────────────
    _w("## Tests")
    _w("")
    if pack.tests.existing_tests:
        _w("### Existing Tests")
        _w("")
        for rt in pack.tests.existing_tests:
            _w(f"- `{rt.test_file}` :: `{rt.test_name}` — {rt.reason}")
        _w("")
    else:
        _w("_No existing tests found related to this task._")
        _w("")

    if pack.tests.suggested_tests:
        _w("### Suggested Tests (Heuristic)")
        _w("")
        _w("_These are naming-convention guesses, NOT directives to write tests._")
        _w("")
        for st in pack.tests.suggested_tests:
            src = st.source.value if hasattr(st.source, 'value') else st.source
            _w(f"- `{st.test_name}` in `{st.test_file}` [{src}, "
               f"confidence: {st.confidence:.2f}] — {st.reason}")
        _w("")

    # ── Warnings ─────────────────────────────────────────────────────
    if pack.warnings:
        _w("## Warnings")
        _w("")
        for w in pack.warnings:
            _w(f"- {w}")
        _w("")

    # ── Pack Notes ───────────────────────────────────────────────────
    if pack.pack_notes:
        _w("## Pack Notes")
        _w("")
        for note in pack.pack_notes:
            ntype = note.type.value if hasattr(note.type, 'value') else note.type
            _w(f"- [{ntype}] {note.message}")
        _w("")

    # ── Token Budget ─────────────────────────────────────────────────
    if pack.token_budget:
        _w("## Token Budget")
        _w("")
        tb = pack.token_budget
        _w(f"- **Max Tokens:** {tb.get('max_tokens', 'N/A')}")
        _w(f"- **Used Tokens:** {tb.get('used_tokens', 'N/A')}")
        _w(f"- **Remaining:** {tb.get('remaining', 'N/A')}")
        _w("")

    # ── Footer ───────────────────────────────────────────────────────
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
