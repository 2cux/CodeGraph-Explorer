"""Context Pack builder — generates task-aware code context packages.

PRD §14 — Context Pack generation pipeline.
Implements the full pipeline:
  task text → intent → keywords → search → ranking → call graph →
  impact → tests → context selection → reading plan → agent instructions → export
"""

import re
from datetime import datetime, timezone
from pathlib import Path

from codegraph.context import ranking
from codegraph.context import reading_plan as rplan
from codegraph.context import markdown_exporter
from codegraph.context.models import (
    AffectedFile,
    AffectedSymbol,
    AgentInstructions,
    CallGraph,
    CallGraphEdge,
    CallGraphNode,
    ContextPack,
    EntryPoint,
    ExportsInfo,
    Impact,
    Importance,
    RecommendedContext,
    RelatedSymbol,
    Risk,
    Task,
    TaskConstraints,
    TaskIntent,
)
from codegraph.graph import impact as graph_impact
from codegraph.graph.models import GraphNode, NodeType, EdgeType
from codegraph.graph.store import GraphStore

# Context types that require source-level task understanding (non-trivial intents)
_IMPACT_INTENTS = frozenset({
    TaskIntent.modify_existing_behavior,
    TaskIntent.fix_bug,
    TaskIntent.refactor,
    TaskIntent.add_feature,
    TaskIntent.analyze_impact,
})


# ── Task parsing helpers ──────────────────────────────────────────────────────


def _parse_intent(task_description: str) -> TaskIntent:
    """Identify task intent from keywords in the description.

    PRD §14.2 step 1 — intent recognition.
    Uses keyword heuristics ordered from most specific to most general.
    """
    text = task_description.lower()

    if any(w in text for w in ("fix", "bug", "error", "broken", "issue", "incorrect")):
        return TaskIntent.fix_bug
    if any(w in text for w in ("add", "new", "implement", "feature", "introduce", "create")):
        return TaskIntent.add_feature
    if any(w in text for w in ("refactor", "clean", "restructure", "reorganize", "simplify", "extract")):
        return TaskIntent.refactor
    if any(w in text for w in ("change", "modify", "update", "revise", "edit")):
        return TaskIntent.modify_existing_behavior
    if any(w in text for w in ("test", "write test", "unit test")):
        return TaskIntent.write_tests
    if any(w in text for w in ("review", "audit")):
        return TaskIntent.review_code
    if any(w in text for w in ("impact", "affect", "what if")):
        return TaskIntent.analyze_impact
    if any(w in text for w in ("doc", "document", "explain", "readme")):
        return TaskIntent.generate_docs

    return TaskIntent.understand_code


def _find_target_symbols(task_description: str) -> list[str]:
    """Extract explicit symbol IDs from task text matching ``file.py::symbol``."""
    return re.findall(r"[\w/\\]+\.\w+::[\w.]+", task_description)


def _search_candidates(
    store: GraphStore,
    keywords: list[str],
    target_symbols: list[str],
) -> list[GraphNode]:
    """Collect candidate nodes by searching the store.

    Priority: explicit target symbols > keyword matches > fallback to all nodes.
    Skips repository, file, and import_ container nodes — only symbol-level nodes
    (function, class, method) are treated as entry point candidates.
    """
    seen: set[str] = set()
    candidates: list[GraphNode] = []

    # 1. Explicitly referenced symbols
    for sym_id in target_symbols:
        node = store.get_node(sym_id)
        if node and node.id not in seen:
            seen.add(node.id)
            candidates.append(node)

    # 2. Keyword-based search
    _skip_types = {NodeType.repository, NodeType.file, NodeType.import_, NodeType.external_symbol}
    for kw in keywords:
        results = store.search_nodes(kw)
        for node in results:
            if node.id not in seen and node.type not in _skip_types:
                seen.add(node.id)
                candidates.append(node)

    # 3. Fallback: all non-trivial symbols when nothing matched
    if not candidates:
        skip = {NodeType.repository, NodeType.file, NodeType.import_, NodeType.external_symbol}
        for node in store.all_nodes():
            if node.type not in skip:
                candidates.append(node)

    return candidates


# ── Context selection with token budgeting ────────────────────────────────────


def _build_recommended_context(
    store: GraphStore,
    entry_points: list[EntryPoint],
    top_entry_nodes: list[GraphNode],
    related_ids: set[str],
    max_tokens: int,
) -> list[RecommendedContext]:
    """Build recommended context list with token budgeting.

    Priority per PRD §14.4:
      1. Entry point source code (critical, full source)
      2. Direct callees (high, full source)
      3. Callers and lower-priority symbols degrade to summary when over budget
      4. Low-confidence symbols omitted from content (go to warnings only)
    """
    ctx_list: list[RecommendedContext] = []
    ctx_count = 0
    used_tokens = 0

    def _make_ctx(
        node: GraphNode,
        priority: str,
        reason: str,
        ctx_type: str = "code_snippet",
    ) -> RecommendedContext | None:
        nonlocal ctx_count, used_tokens

        content = node.code_preview or ""
        estimated = len(content) // 4

        # Degrade if over budget (except critical items)
        if used_tokens + estimated > max_tokens and priority != "critical":
            content = (
                f"Symbol: {node.name}\n"
                f"Type: {node.type.value}\n"
                f"File: {node.file_path}\n"
                f"Signature: {node.signature or 'N/A'}"
            )
            estimated = len(content) // 4
            if used_tokens + estimated > max_tokens:
                # Summary also over budget — skip entirely
                # (callers / low-pri will appear in related_symbols list)
                return None

        ctx_count += 1
        loc = node.location
        used_tokens += max(estimated, 1)
        return RecommendedContext(
            context_id=f"ctx_item_{ctx_count:03d}",
            type=ctx_type,
            symbol_id=node.id,
            file_path=node.file_path or "",
            line_start=loc.line_start if loc else 0,
            line_end=loc.line_end if loc else 0,
            priority=priority,
            reason=reason,
            content=content,
            estimated_tokens=estimated,
        )

    # Level 1: Entry points (critical, full source)
    ep_map = {n.id: n for n in top_entry_nodes}
    for ep in entry_points:
        node = ep_map.get(ep.symbol_id) or store.get_node(ep.symbol_id)
        if node:
            ctx = _make_ctx(node, "critical", ep.reason or "Main entry point for task")
            if ctx:
                ctx_list.append(ctx)

    # Level 2: Related symbols (high priority, full source if budget allows)
    for sym_id in sorted(related_ids):
        if used_tokens >= max_tokens:
            break
        if sym_id in {ep.symbol_id for ep in entry_points}:
            continue
        node = store.get_node(sym_id)
        if node:
            ctx = _make_ctx(node, "high", "Related symbol — downstream dependency or caller")
            if ctx:
                ctx_list.append(ctx)

    return ctx_list


# ── Agent instructions ────────────────────────────────────────────────────────


def _build_agent_instructions(
    task_description: str,
    intent: TaskIntent,
    entry_points: list[EntryPoint],
    related_count: int,
    warnings: list[str],
) -> AgentInstructions:
    """Generate agent-facing instructions — PRD §13.9.

    Includes summary, recommended strategy steps, and warnings.
    """
    strategy: list[str] = []

    if entry_points:
        ep_list = ", ".join(ep.symbol_id for ep in entry_points[:3])
        strategy.append(f"Read the entry point first: {ep_list}.")
    if related_count > 0:
        strategy.append(f"Inspect {related_count} related symbol(s) for dependencies and callers.")
    strategy.append("Review the call graph to understand upstream callers and downstream callees.")

    if intent in _IMPACT_INTENTS:
        strategy.append("Run impact analysis and review affected files before making changes.")
        strategy.append("Update related tests to cover the changes.")
    elif intent == TaskIntent.write_tests:
        strategy.append("Focus on test files related to the target symbols.")
        strategy.append("Ensure edge cases and error paths are covered in tests.")
    elif intent == TaskIntent.understand_code:
        strategy.append("Follow the reading plan in order for progressive code understanding.")

    entry_names = ", ".join(ep.name for ep in entry_points[:5]) if entry_points else "N/A"
    summary = (
        f"Task focuses on symbols: {entry_names}. "
        f"Identified intent: {intent.value}. "
        f"The context pack includes {len(entry_points)} entry point(s), "
        f"{related_count} related symbol(s), and a reading plan."
    )

    return AgentInstructions(
        summary=summary,
        recommended_strategy=strategy,
        warnings=warnings,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def build_context_pack(
    store: GraphStore,
    task_description: str,
    query: str = "",
    target_symbols: list[str] | None = None,
    max_tokens: int = 32000,
    max_files: int = 8,
    include_tests: bool = True,
    depth: int = 2,
    output_dir: str | None = None,
) -> ContextPack:
    """Build a Context Pack from the graph store for the given task.

    This is the main orchestrator implementing the PRD §14 pipeline:

      1. Intent identification + keyword extraction (§14.2 steps 1-2)
      2. Symbol search (§14.2 step 3)
      3. Entry point ranking (§14.2 step 4, §14.3)
      4. Call graph expansion (§14.2 step 5)
      5. Impact analysis (§14.2 step 6)
      6. Related test discovery (§14.2 step 7)
      7. Recommended context with token budgeting (§14.2 step 8, §14.4-14.5)
      8. Reading plan generation (§14.2 step 9)
      9. Agent instructions (§14.2 step 10)
      10. JSON + Markdown export (§14.2 step 11)
    """
    # ── Step 1-2: Parse task → intent + keywords ─────────────────────────
    intent = _parse_intent(task_description)
    keywords = ranking.tokenize(task_description)
    parsed_targets = _find_target_symbols(task_description)
    all_targets = list(set((target_symbols or []) + parsed_targets))

    task = Task(
        raw_request=task_description,
        intent=intent,
        keywords=keywords,
        target_symbols=all_targets,
        constraints=TaskConstraints(
            max_tokens=max_tokens,
            max_files=max_files,
            include_tests=include_tests,
        ),
    )

    # ── Step 3-4: Search + rank entry points ──────────────────────────────
    candidates = _search_candidates(store, keywords or ["_"], all_targets)
    ranked = ranking.rank_entry_points(task_description, candidates)

    top_n = min(max_files, len(ranked))
    top_ranked = ranked[:top_n]

    tokens = ranking.tokenize(task_description)
    entry_points: list[EntryPoint] = []
    top_entry_nodes: list[GraphNode] = []
    for node, score in top_ranked:
        sources = ranking.get_match_sources(node, tokens)
        reason = ranking.build_reason(node, tokens)
        entry_points.append(EntryPoint(
            symbol_id=node.id,
            type=node.type.value,
            name=node.name,
            file_path=node.file_path,
            location=node.location.model_dump() if node.location else None,
            signature=node.signature,
            reason=reason,
            score=score,
            match_sources=sources,
        ))
        top_entry_nodes.append(node)

    # ── Step 5: Expand call graph + collect related symbols ──────────────
    related_symbols: list[RelatedSymbol] = []
    related_ids: set[str] = set()
    call_nodes: list[CallGraphNode] = []
    call_edges: list[CallGraphEdge] = []
    center_id = entry_points[0].symbol_id if entry_points else ""

    for node in top_entry_nodes:
        # Outgoing edges (callees)
        for edge in store.get_outgoing_edges(node.id):
            if edge.type == EdgeType.calls and edge.target not in related_ids:
                related_ids.add(edge.target)
                related_symbols.append(RelatedSymbol(
                    symbol_id=edge.target,
                    relation="callee",
                    distance=1,
                    direction="outgoing",
                    reason=f"Called by {node.name}",
                    importance=Importance.high,
                    confidence=edge.confidence,
                ))
            if edge.type == EdgeType.calls:
                target_node = store.get_node(edge.target)
                if target_node:
                    call_nodes.append(CallGraphNode(
                        id=target_node.id, label=target_node.name, type=target_node.type.value,
                    ))
                call_edges.append(CallGraphEdge(
                    source=node.id, target=edge.target, type="calls", confidence=edge.confidence,
                ))

        # Incoming edges (callers)
        for edge in store.get_incoming_edges(node.id):
            if edge.type == EdgeType.calls and edge.source not in related_ids:
                related_ids.add(edge.source)
                related_symbols.append(RelatedSymbol(
                    symbol_id=edge.source,
                    relation="caller",
                    distance=1,
                    direction="incoming",
                    reason=f"Calls {node.name}",
                    importance=Importance.medium,
                    confidence=edge.confidence,
                ))
            if edge.type == EdgeType.calls:
                source_node = store.get_node(edge.source)
                if source_node:
                    call_nodes.append(CallGraphNode(
                        id=source_node.id, label=source_node.name, type=source_node.type.value,
                    ))
                call_edges.append(CallGraphEdge(
                    source=edge.source, target=node.id, type="calls", confidence=edge.confidence,
                ))

        # Entry point itself in call graph
        call_nodes.append(CallGraphNode(
            id=node.id, label=node.name, type=node.type.value,
        ))

    # Deduplicate
    seen_ids: set[str] = set()
    deduped_nodes = [n for n in call_nodes if not (n.id in seen_ids or seen_ids.add(n.id))]
    seen_keys: set[tuple[str, str]] = set()
    deduped_edges = [
        e for e in call_edges
        if not ((e.source, e.target) in seen_keys or seen_keys.add((e.source, e.target)))
    ]

    call_graph = CallGraph(center=center_id, depth=depth, nodes=deduped_nodes, edges=deduped_edges)

    # ── Step 6: Impact analysis (for modify/fix/refactor/add tasks) ──────
    impact = Impact()
    if entry_points and intent in _IMPACT_INTENTS:
        primary_id = entry_points[0].symbol_id
        result = graph_impact.analyze_impact(store, primary_id, depth=depth)

        impact = Impact(
            changed_symbol=result.get("changed_symbol", primary_id),
            affected_symbols=[
                AffectedSymbol(
                    symbol_id=s["symbol_id"],
                    reason=s.get("reason", ""),
                    impact_type=s.get("impact_type", "unknown"),
                    distance=s.get("distance", 1),
                    confidence=s.get("confidence", 0.0),
                )
                for s in result.get("affected_symbols", [])
            ],
            affected_files=[
                AffectedFile(
                    file_path=f["file_path"],
                    reason=f.get("reason", ""),
                    priority=f.get("priority", "medium"),
                )
                for f in result.get("affected_files", [])
            ],
            risk=Risk(
                level=result.get("risk", {}).get("level", "low"),
                reasons=result.get("risk", {}).get("reasons", []),
            ),
        )

        # Merge impact symbols into related_ids
        for s in impact.affected_symbols:
            related_ids.add(s.symbol_id)

    # ── Step 7: Discover related tests ────────────────────────────────────
    test_ids: list[str] = []
    if include_tests:
        ep_names_lower = {ep.name.lower() for ep in entry_points}
        for node in store.all_nodes():
            if node.type != NodeType.test:
                continue
            # Match test name against entry point names
            if any(ep_name in node.name.lower() for ep_name in ep_names_lower):
                if node.id not in related_ids:
                    related_ids.add(node.id)
                    related_symbols.append(RelatedSymbol(
                        symbol_id=node.id,
                        relation="test",
                        distance=2,
                        direction="incoming",
                        reason=f"Related test — name references task symbol",
                        importance=Importance.high,
                        confidence=0.7,
                    ))
                    test_ids.append(node.id)
                continue

            # Match tests that call entry points or related symbols
            for edge in store.get_outgoing_edges(node.id):
                if edge.type == EdgeType.calls and edge.target in related_ids:
                    if node.id not in related_ids:
                        related_ids.add(node.id)
                        related_symbols.append(RelatedSymbol(
                            symbol_id=node.id,
                            relation="test",
                            distance=2,
                            direction="outgoing",
                            reason=f"Calls task-related symbol {edge.target}",
                            importance=Importance.high,
                            confidence=edge.confidence or 0.7,
                        ))
                        test_ids.append(node.id)
                    break

    # ── Step 8: Select recommended context (with token budget) ────────────
    recommended_context = _build_recommended_context(
        store, entry_points, top_entry_nodes, related_ids, max_tokens,
    )

    # ── Step 9: Build reading plan ────────────────────────────────────────
    callee_ids = [rs.symbol_id for rs in related_symbols if rs.relation == "callee"]
    caller_ids = [rs.symbol_id for rs in related_symbols if rs.relation == "caller"]
    entry_ids = [ep.symbol_id for ep in entry_points]

    reading_plan = rplan.build_reading_plan(
        entry_point_ids=entry_ids,
        callee_ids=callee_ids,
        caller_ids=caller_ids,
        test_ids=test_ids,
        max_steps=max_files + 4,
    )

    # ── Step 10: Build agent instructions ─────────────────────────────────
    warnings: list[str] = []
    low_conf_edges = [e for e in call_edges if e.confidence < 0.6]
    if low_conf_edges:
        warnings.append(
            f"{len(low_conf_edges)} edge(s) have confidence below 0.6 — "
            "treat these relationships as weak signals."
        )
    if not entry_points:
        warnings.append(
            "No entry points found — the task may not match the indexed codebase."
        )

    agent_instructions = _build_agent_instructions(
        task_description, intent, entry_points, len(related_symbols), warnings,
    )

    # ── Step 11: Assemble Context Pack ────────────────────────────────────
    first_kw = keywords[0] if keywords else "pack"
    pack_id = (
        f"ctx_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{first_kw}"
        .replace("/", "_").replace("\\", "_")
    )

    # Collect minimal repo info
    all_nodes = store.all_nodes()
    repo_info: dict = {}
    if all_nodes:
        first = all_nodes[0]
        repo_info = {
            "symbol_count": store.node_count(),
            "edge_count": store.edge_count(),
        }
        if first.file_path:
            repo_info["name"] = first.file_path.split("/")[0]

    pack = ContextPack(
        schema_version="1.0.0",
        pack_id=pack_id,
        task=task,
        repo=repo_info,
        entry_points=entry_points,
        related_symbols=related_symbols,
        call_graph=call_graph,
        impact=impact,
        recommended_context=recommended_context,
        reading_plan=reading_plan,
        agent_instructions=agent_instructions,
        exports=ExportsInfo(),
    )

    # ── Step 12: Export JSON + Markdown ───────────────────────────────────
    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        json_path = out_path / f"{pack_id}.json"
        json_path.write_text(
            pack.model_dump_json(indent=2, exclude_none=True), encoding="utf-8",
        )

        md_path = out_path / f"{pack_id}.md"
        markdown_exporter.save_markdown(pack, str(md_path))

        pack.exports = ExportsInfo(
            markdown_path=str(md_path),
            json_path=str(json_path),
        )

    return pack
