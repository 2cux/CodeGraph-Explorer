"""Evidence Pack builder — generates task-aware structured code evidence.

Pipeline:
  task text → intent → keywords → search → ranking → call graph →
  impact → tests → context selection → warnings → pack notes → export

Output is an Evidence Pack: structured code facts (relationships,
confidence, evidence sources). No reading plans, execution orders,
or agent instructions.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

from codegraph.context import ranking
from codegraph.context import markdown_exporter
from codegraph.context.selection import ContextSelector
from codegraph.context.strategies import analyze_task, compose_strategy, classify_task_intent, get_strategy
from codegraph.context.token_budget import estimate_tokens
from codegraph.context.models import (
    AffectedFile,
    AffectedSymbol,
    CallGraph,
    CallGraphEdge,
    CallGraphNode,
    ConfidenceLevel,
    ContentMode,
    ContextPack,
    ContextType,
    Direction,
    EntryPoint,
    EntryPointLocation,
    ExportsInfo,
    Impact,
    Importance,
    IndexStatus,
    NoteType,
    PackNote,
    PriorityLevel,
    RelatedSymbol,
    RelatedTest,
    RelationType,
    Risk,
    SelectedContext,
    Task,
    TaskConstraints,
    TaskIntent,
    TestSource,
    TestsSection,
)
from codegraph.graph import impact as graph_impact
from codegraph.graph.confidence import get_confidence_level, is_low_confidence
from codegraph.graph.models import GraphNode, NodeType, EdgeType
from codegraph.graph.store import GraphStore



def _find_target_symbols(task_description: str) -> list[str]:
    """Extract explicit symbol IDs from task text matching ``file.py::symbol``."""
    return re.findall(r"[\w/\\]+\.\w+::[\w.]+", task_description)


def _search_candidates(
    store: GraphStore,
    keywords: list[str],
    target_symbols: list[str],
) -> list[GraphNode]:
    """Collect candidate nodes by searching the store."""
    seen: set[str] = set()
    candidates: list[GraphNode] = []

    _skip_types = {NodeType.repository, NodeType.file, NodeType.module, NodeType.import_, NodeType.external_symbol}

    # 1. Explicitly referenced symbols
    for sym_id in target_symbols:
        node = store.get_node(sym_id)
        if node and node.id not in seen:
            seen.add(node.id)
            candidates.append(node)

    # 2. Keyword-based search
    for kw in keywords:
        results = store.search_nodes(kw)
        for node in results:
            if node.id not in seen and node.type not in _skip_types:
                seen.add(node.id)
                candidates.append(node)

    # 3. Fallback: all non-trivial symbols
    if not candidates:
        skip = {NodeType.repository, NodeType.file, NodeType.module, NodeType.import_, NodeType.external_symbol}
        for node in store.all_nodes():
            if node.type not in skip:
                candidates.append(node)

    return candidates


# ── Model/config/store dependency discovery ──────────────────────────


def _find_model_config_store_deps(
    store: GraphStore,
    entry_points: list[EntryPoint],
    related_ids: set[str],
) -> list[tuple[str, str, str, float]]:
    """Find model/config/store nodes imported by files in the call graph.

    Returns list of ``(symbol_id, relation, reason, confidence)`` tuples.
    """
    result: list[tuple[str, str, str, float]] = []
    seen: set[str] = set()

    file_ids: set[str] = set()
    for ep in entry_points:
        if ep.file_path:
            file_ids.add(ep.file_path)
    for sym_id in related_ids:
        parts = sym_id.split("::", 1)
        if parts[0]:
            file_ids.add(parts[0])

    qual_to_class: dict[str, GraphNode] = {}
    for node in store.all_nodes():
        if node.type == NodeType.class_ and node.qualified_name:
            qual_to_class[node.qualified_name] = node

    for file_id in file_ids:
        import_edges = store.get_outgoing_edges(file_id)
        for edge in import_edges:
            if edge.type != EdgeType.imports:
                continue
            import_node = store.get_node(edge.target)
            if not import_node or not import_node.qualified_name:
                continue
            class_node = qual_to_class.get(import_node.qualified_name)
            if not class_node:
                continue
            if class_node.id in seen:
                continue

            tags = class_node.tags
            class_name = class_node.name
            if "model" in tags and "config" not in tags:
                seen.add(class_node.id)
                result.append((
                    class_node.id, "model_dependency", 2,
                    f"Data model `{class_name}` — may require field additions or schema changes.",
                ))
            elif "config" in tags or "settings" in tags:
                seen.add(class_node.id)
                result.append((
                    class_node.id, "config_dependency", 2,
                    f"Configuration `{class_name}` — may need new config fields or settings.",
                ))
            elif "store" in tags or "persistence" in tags:
                seen.add(class_node.id)
                result.append((
                    class_node.id, "persistence_dependency", 2,
                    f"Persistence `{class_name}` — may need corresponding store/repository updates.",
                ))
            elif "schema" in tags:
                seen.add(class_node.id)
                result.append((
                    class_node.id, "schema_dependency", 2,
                    f"Schema `{class_name}` — data structure changes may require schema updates.",
                ))

    return result


# ── Test discovery ───────────────────────────────────────────────────


def _discover_related_tests(
    store: GraphStore,
    entry_points: list[EntryPoint],
    related_ids: set[str],
) -> tuple[list[RelatedTest], list[RelatedTest], list[str]]:
    """Discover existing tests and generate heuristic suggestions.

    Returns ``(existing_tests, suggested_tests, test_ids)``.
    Suggested tests use ``source="heuristic"`` — they are naming-convention
    guesses, NOT directives to write tests.
    """
    existing_tests: list[RelatedTest] = []
    suggested_tests: list[RelatedTest] = []
    test_ids: list[str] = []
    ep_names_lower = {ep.name.lower() for ep in entry_points}
    entry_symbol_ids = {ep.symbol_id for ep in entry_points}
    seen_test_ids: set[str] = set()

    def _add_existing(node: GraphNode, reason: str, confidence: float) -> None:
        if node.id in seen_test_ids:
            return
        seen_test_ids.add(node.id)
        if node.id not in related_ids:
            related_ids.add(node.id)
        existing_tests.append(RelatedTest(
            source=TestSource.existing,
            test_file=node.file_path or "",
            test_name=node.name,
            reason=reason,
            confidence=confidence,
            confidence_level=ConfidenceLevel(get_confidence_level(confidence)),
        ))
        test_ids.append(node.id)

    # Phase 1a: tested_by edges
    for ep_id in entry_symbol_ids:
        for edge in store.get_outgoing_edges(ep_id):
            if edge.type == EdgeType.tested_by:
                test_node = store.get_node(edge.target)
                if test_node and test_node.type == NodeType.test:
                    _add_existing(
                        test_node,
                        reason=f"Test directly covers `{test_node.name}` via tested_by edge.",
                        confidence=edge.confidence,
                    )

    # Phase 1b–1c: name / call matches
    for node in store.all_nodes():
        if node.type != NodeType.test:
            continue
        if node.id in seen_test_ids:
            continue

        test_base = node.name
        if test_base.startswith("test_"):
            test_base = test_base[len("test_"):]
        parts = test_base.split("_")
        matched = False
        for i in range(len(parts), 0, -1):
            candidate = "_".join(parts[:i])
            if candidate in ep_names_lower:
                _add_existing(
                    node,
                    reason=f"Test name `{node.name}` matches task symbol `{candidate}`.",
                    confidence=0.7,
                )
                matched = True
                break
        if matched:
            continue

        for edge in store.get_outgoing_edges(node.id):
            if edge.type == EdgeType.calls and edge.target in related_ids:
                target_node = store.get_node(edge.target)
                target_name = target_node.name if target_node else edge.target
                _add_existing(
                    node,
                    reason=f"Test calls task-related symbol `{target_name}`.",
                    confidence=edge.confidence or 0.7,
                )
                break

    # Phase 2: Heuristic suggestions (NOT directives)
    if not existing_tests:
        for ep in entry_points:
            file_path = ep.file_path or ""
            module_name = file_path.split("/")[-1].replace(".py", "") if file_path else ""
            test_path = f"tests/test_{module_name}.py"

            suggested_tests.append(RelatedTest(
                source=TestSource.heuristic,
                test_file=test_path,
                test_name=f"test_{module_name}",
                reason=f"Heuristic: naming convention suggests test module for {file_path or ep.name}.",
                confidence=0.5,
                confidence_level=ConfidenceLevel(get_confidence_level(0.5)),
            ))
            ep_name = ep.name.lower()
            for suffix in ("success", "valid", "basic", "happy_path", "error", "invalid",
                           "missing", "edge_case"):
                suggested_tests.append(RelatedTest(
                    source=TestSource.heuristic,
                    test_file=test_path,
                    test_name=f"test_{ep_name}_{suffix}",
                    reason=f"Heuristic: common test pattern — {suffix.replace('_', ' ')} scenario for `{ep_name}`.",
                    confidence=0.5,
                    confidence_level=ConfidenceLevel(get_confidence_level(0.5)),
                ))

    return existing_tests, suggested_tests, test_ids


# ── Pack notes ───────────────────────────────────────────────────────


def _build_pack_notes(
    store: GraphStore,
    entry_points: list[EntryPoint],
    pack_warnings: list[str],
    token_budget: dict[str, int],
) -> list[PackNote]:
    """Generate factual pack_notes — metadata about the pack, not advice."""
    notes: list[PackNote] = []

    # Index status note
    notes.append(PackNote(
        type=NoteType.index_status,
        message=f"Index contains {store.node_count()} symbols and {store.edge_count()} edges.",
        details={"symbol_count": store.node_count(), "edge_count": store.edge_count()},
    ))

    # Token budget note
    notes.append(PackNote(
        type=NoteType.token_budget,
        message=f"Token budget: {token_budget.get('max_tokens', 'N/A')} max, "
                f"{token_budget.get('used_tokens', 'N/A')} used, "
                f"{token_budget.get('remaining', 'N/A')} remaining.",
        details=token_budget,
    ))

    # Competing entry points note
    if len(entry_points) > 1:
        ep_names = [ep.name for ep in entry_points[:5]]
        notes.append(PackNote(
            type=NoteType.competing_entry_points,
            message=f"Multiple candidate entry points matched: {', '.join(ep_names)}. "
                    f"All are included as candidates — no single entry point is prescribed.",
            details={"candidate_count": len(entry_points), "candidates": ep_names},
        ))

    # Test coverage signal
    notes.append(PackNote(
        type=NoteType.test_coverage_signal,
        message="Suggested tests are generated from naming conventions (source=heuristic). "
                "They indicate where tests MIGHT exist or be placed, not directives to create them.",
        details={},
    ))

    # Warning count
    if pack_warnings:
        notes.append(PackNote(
            type=NoteType.confidence,
            message=f"{len(pack_warnings)} warning(s) about low-confidence signals in this pack.",
            details={"warning_count": len(pack_warnings)},
        ))

    return notes


# ── Build entry point evidence ────────────────────────────────────────


def _build_ep_evidence(ep: EntryPoint, node: GraphNode | None) -> str:
    """Describe the evidence for why this entry point was selected."""
    sources = ", ".join(ep.match_sources) if ep.match_sources else "keyword match"
    if node and node.type:
        return f"Matched by {sources} (node type: {node.type.value}, score: {ep.score:.2f})"
    return f"Matched by {sources} (score: {ep.score:.2f})"


# ── Public API ───────────────────────────────────────────────────────


# Hard max token budget for Evidence Pack — enforced at builder level
HARD_MAX_TOKENS = 20000


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
    debug_plan: bool = False,
) -> ContextPack:
    """Build an Evidence Pack from the graph store for the given task.

    Pipeline:
      1. Intent identification + keyword extraction
      2. Symbol search
      3. Entry point ranking
      4. Call graph expansion
      5. Impact analysis
      6. Related test discovery
      7. Context selection with token budgeting
      8. Warnings collection
      9. Pack notes generation
      10. JSON + Markdown export
    """
    # ── Step 0: Clamp max_tokens to hard max ───────────────────────────
    max_tokens = max(100, min(max_tokens, HARD_MAX_TOKENS))

    # ── Step 1-2: Parse task → intent + keywords + strategy ──────────
    profile = analyze_task(task_description)
    intent = profile.primary_intent
    strategy = compose_strategy(profile)
    keywords = profile.keywords if profile.keywords else ranking.tokenize(task_description)
    parsed_targets = _find_target_symbols(task_description)
    all_targets = list(set((target_symbols or []) + parsed_targets))

    task = Task(
        raw_request=task_description,
        intent=intent,
        primary_intent=profile.primary_intent,
        secondary_intents=profile.secondary_intents,
        keywords=keywords,
        target_symbols=all_targets,
        constraints=TaskConstraints(
            max_tokens=max_tokens,
            max_files=max_files,
            include_tests=include_tests,
        ),
    )

    # ── Step 3-4: Search + rank entry points ─────────────────────────
    candidates = _search_candidates(store, keywords or ["_"], all_targets)
    ranked = ranking.rank_entry_points(task_description, candidates)
    if not ranked and candidates:
        ranked = [(c, 0.5) for c in candidates[:max_files]]

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
            location=EntryPointLocation(
                line_start=node.location.line_start or 0,
                line_end=node.location.line_end or 0,
                column_start=node.location.column_start or 0,
                column_end=node.location.column_end or 0,
            ) if node.location else None,
            signature=node.signature,
            reason=reason,
            score=score,
            match_sources=sources,
        ))
        top_entry_nodes.append(node)

    # ── Step 5: Expand call graph + collect related symbols ──────────
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
                    relation=RelationType.callee,
                    distance=1,
                    direction=Direction.outgoing,
                    reason=f"Called by `{node.name}` — direct downstream dependency.",
                    importance=Importance.high,
                    confidence=edge.confidence,
                    confidence_level=ConfidenceLevel(get_confidence_level(edge.confidence)),
                ))
            if edge.type == EdgeType.calls:
                target_node = store.get_node(edge.target)
                if target_node:
                    call_nodes.append(CallGraphNode(
                        id=target_node.id, label=target_node.name, type=target_node.type.value,
                    ))
                call_edges.append(CallGraphEdge(
                    source=node.id, target=edge.target, type="calls",
                    confidence=edge.confidence,
                    resolution=edge.metadata.resolution.value if edge.metadata and edge.metadata.resolution else "",
                    confidence_level=ConfidenceLevel(get_confidence_level(edge.confidence)),
                ))

        # Incoming edges (callers)
        for edge in store.get_incoming_edges(node.id):
            if edge.type == EdgeType.calls and edge.source not in related_ids:
                related_ids.add(edge.source)
                related_symbols.append(RelatedSymbol(
                    symbol_id=edge.source,
                    relation=RelationType.caller,
                    distance=1,
                    direction=Direction.incoming,
                    reason=f"Calls `{node.name}` — upstream consumer.",
                    importance=Importance.medium,
                    confidence=edge.confidence,
                    confidence_level=ConfidenceLevel(get_confidence_level(edge.confidence)),
                ))
            if edge.type == EdgeType.calls:
                source_node = store.get_node(edge.source)
                if source_node:
                    call_nodes.append(CallGraphNode(
                        id=source_node.id, label=source_node.name, type=source_node.type.value,
                    ))
                call_edges.append(CallGraphEdge(
                    source=edge.source, target=node.id, type="calls",
                    confidence=edge.confidence,
                    resolution=edge.metadata.resolution.value if edge.metadata and edge.metadata.resolution else "",
                    confidence_level=ConfidenceLevel(get_confidence_level(edge.confidence)),
                ))

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

    # ── Step 6: Impact analysis ──────────────────────────────────────
    impact = Impact()
    if entry_points and strategy.impact_required:
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
                    confidence_level=ConfidenceLevel(get_confidence_level(s.get("confidence", 0.0))),
                )
                for s in result.get("affected_symbols", [])
            ],
            affected_files=[
                AffectedFile(
                    file_path=f["file_path"],
                    reason=f.get("reason", ""),
                    priority=PriorityLevel(f.get("priority", "medium")),
                )
                for f in result.get("affected_files", [])
            ],
            risk=Risk(
                level=result.get("risk", {}).get("level", "low"),
                reasons=result.get("risk", {}).get("reasons", []),
            ),
        )

        for s in impact.affected_symbols:
            related_ids.add(s.symbol_id)

    # ── Step 6.5: Discover model / config / store dependencies ───────
    mcs_deps = _find_model_config_store_deps(store, entry_points, related_ids)
    model_ids: list[str] = []
    config_ids: list[str] = []
    store_ids: list[str] = []
    for sym_id, relation, dist, reason in mcs_deps:
        if sym_id not in related_ids:
            related_ids.add(sym_id)
        confidence = 0.85
        if relation == "model_dependency":
            importance = Importance.high
            model_ids.append(sym_id)
            rel_type = RelationType.model_dependency
        elif relation == "config_dependency":
            importance = Importance.high
            config_ids.append(sym_id)
            rel_type = RelationType.config_dependency
        elif relation == "persistence_dependency":
            importance = Importance.high
            store_ids.append(sym_id)
            rel_type = RelationType.persistence_dependency
        elif relation == "schema_dependency":
            importance = Importance.medium
            model_ids.append(sym_id)
            rel_type = RelationType.schema_dependency
        else:
            importance = Importance.medium
            rel_type = RelationType.related
        related_symbols.append(RelatedSymbol(
            symbol_id=sym_id,
            relation=rel_type,
            distance=dist,
            direction=Direction.outgoing,
            reason=reason,
            importance=importance,
            confidence=confidence,
            confidence_level=ConfidenceLevel(get_confidence_level(confidence)),
        ))

    # ── Step 7: Discover related tests ───────────────────────────────
    existing_tests: list[RelatedTest] = []
    suggested_tests: list[RelatedTest] = []
    test_ids: list[str] = []
    if include_tests:
        existing_tests, suggested_tests, test_ids = _discover_related_tests(store, entry_points, related_ids)

        for rt in existing_tests:
            if rt.source != TestSource.existing:
                continue
            test_sym_id = rt.test_file
            if test_sym_id not in {rs.symbol_id for rs in related_symbols}:
                related_symbols.append(RelatedSymbol(
                    symbol_id=test_sym_id,
                    relation=RelationType.test,
                    distance=2,
                    direction=Direction.incoming,
                    reason=rt.reason,
                    importance=Importance.high,
                    confidence=rt.confidence,
                    confidence_level=ConfidenceLevel(get_confidence_level(rt.confidence)),
                ))

    # ── Step 8: Select context (with token budget) ───────────────────
    selector = ContextSelector(store, task_description, max_tokens, strategy)

    # Entry points as SelectedContext
    ep_context: list[SelectedContext] = []
    for i, ep in enumerate(entry_points):
        node = store.get_node(ep.symbol_id)
        content = node.code_preview if node and node.code_preview else ""
        loc = node.location if node else None
        ep_context.append(SelectedContext(
            context_id=f"ctx_item_{i + 1:03d}",
            type=ContextType.code_snippet,
            symbol_id=ep.symbol_id,
            file_path=ep.file_path,
            line_start=loc.line_start if loc else 0,
            line_end=loc.line_end if loc else 0,
            priority=PriorityLevel.critical,
            relation="entry_point",
            selection_reason=ep.reason or "Candidate entry point matched by keyword search.",
            content=content,
            estimated_tokens=estimate_tokens(content),
            content_mode=ContentMode.full_source,
            confidence=ep.score,
            confidence_level=ConfidenceLevel(get_confidence_level(ep.score)),
            resolution="",
            evidence=_build_ep_evidence(ep, node),
        ))
        selector.budget.spend(estimate_tokens(content))

    sel_high, sel_low = selector.select(entry_points, related_symbols)
    selected_context = ep_context + sel_high + sel_low

    # ── Step 9: Collect warnings ─────────────────────────────────────
    warnings: list[str] = []

    low_conf_edges = [e for e in call_edges if is_low_confidence(e.confidence)]
    if low_conf_edges:
        edge_details = ", ".join(
            f"{e.source.split('::')[-1]}→{e.target.split('::')[-1]} ({e.confidence:.2f})"
            for e in low_conf_edges[:5]
        )
        warnings.append(
            f"{len(low_conf_edges)} call graph edge(s) have confidence below 0.60: {edge_details}"
        )

    low_conf_symbols = [rs for rs in related_symbols if is_low_confidence(rs.confidence)]
    if low_conf_symbols:
        sym_details = ", ".join(
            f"{rs.symbol_id.split('::')[-1]} ({rs.relation.value if hasattr(rs.relation, 'value') else rs.relation}, {rs.confidence:.2f})"
            for rs in low_conf_symbols[:5]
        )
        warnings.append(
            f"{len(low_conf_symbols)} related symbol(s) have low confidence: {sym_details}"
        )

    if not entry_points:
        warnings.append("No entry points found — the task may not match the indexed codebase.")

    # ── Step 10: Build pack notes ────────────────────────────────────
    token_budget_dict = selector.budget.as_dict()
    pack_notes = _build_pack_notes(store, entry_points, warnings, token_budget_dict)

    # ── Step 11: Assemble Evidence Pack ──────────────────────────────
    first_kw = keywords[0] if keywords else "pack"
    pack_id = (
        f"ctx_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{first_kw}"
        .replace("/", "_").replace("\\", "_")
    )

    all_nodes = store.all_nodes()
    index_status = IndexStatus(
        symbol_count=store.node_count(),
        edge_count=store.edge_count(),
        index_format="codegraph/v1",
        language="python",
    )

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
        created_at=datetime.now(timezone.utc).isoformat(),
        task=task,
        repo=repo_info,
        index_status=index_status,
        entry_points=entry_points,
        related_symbols=related_symbols,
        call_graph=call_graph,
        impact=impact,
        tests=TestsSection(
            existing_tests=existing_tests,
            suggested_tests=suggested_tests,
        ),
        selected_context=selected_context,
        warnings=warnings,
        pack_notes=pack_notes,
        exports=ExportsInfo(),
        token_budget=token_budget_dict,
    )

    # ── Step 12: Export JSON + Markdown ──────────────────────────────
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
