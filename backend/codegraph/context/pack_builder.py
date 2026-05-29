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
from codegraph.context.selection import ContextSelector
from codegraph.context.token_budget import estimate_tokens
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
    RelatedTest,
    Risk,
    Task,
    TaskConstraints,
    TaskIntent,
)
from codegraph.graph import impact as graph_impact
from codegraph.graph.confidence import get_confidence_level, is_low_confidence
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

    # "test" must be checked before "add" so "add tests for X" doesn't match add_feature
    if any(w in text for w in ("write test", "add test", "test", "spec", "unit test")):
        return TaskIntent.write_tests
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
    _skip_types = {NodeType.repository, NodeType.file, NodeType.module, NodeType.import_, NodeType.external_symbol}
    for kw in keywords:
        results = store.search_nodes(kw)
        for node in results:
            if node.id not in seen and node.type not in _skip_types:
                seen.add(node.id)
                candidates.append(node)

    # 3. Fallback: all non-trivial symbols when nothing matched
    if not candidates:
        skip = {NodeType.repository, NodeType.file, NodeType.module, NodeType.import_, NodeType.external_symbol}
        for node in store.all_nodes():
            if node.type not in skip:
                candidates.append(node)

    return candidates


# ── Agent instructions ────────────────────────────────────────────────────────


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

    # Collect file_ids from entry points and related symbols
    file_ids: set[str] = set()
    for ep in entry_points:
        if ep.file_path:
            file_ids.add(ep.file_path)
    for sym_id in related_ids:
        parts = sym_id.split("::", 1)
        if parts[0]:
            file_ids.add(parts[0])

    # Build qualified_name → class node lookup
    qual_to_class: dict[str, GraphNode] = {}
    for node in store.all_nodes():
        if node.type == NodeType.class_ and node.qualified_name:
            qual_to_class[node.qualified_name] = node

    # For each file, trace imports → find model/config/store classes
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
                    f"Data model `{class_name}` — modifying features may require field additions or schema changes.",
                ))
            elif "config" in tags or "settings" in tags:
                seen.add(class_node.id)
                result.append((
                    class_node.id, "config_dependency", 2,
                    f"Configuration `{class_name}` — feature changes may need new config fields or settings.",
                ))
            elif "store" in tags or "persistence" in tags:
                seen.add(class_node.id)
                result.append((
                    class_node.id, "persistence_dependency", 2,
                    f"Persistence `{class_name}` — new or changed behavior may need corresponding store/repository updates.",
                ))
            elif "schema" in tags:
                seen.add(class_node.id)
                result.append((
                    class_node.id, "schema_dependency", 2,
                    f"Schema `{class_name}` — data structure changes may require schema updates.",
                ))

    return result


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


# ── Related tests ─────────────────────────────────────────────────────────────


def _discover_related_tests(
    store: GraphStore,
    entry_points: list[EntryPoint],
    related_ids: set[str],
) -> tuple[list[RelatedTest], list[RelatedTest], list[str]]:
    """Discover existing tests and generate suggestions.

    Phase 1: Find tests in the index via three strategies:
      1a. ``tested_by`` edges from entry point symbols (strongest signal).
      1b. Direct name matching — test function name contains an entry point name.
      1c. Call graph — test node has outgoing ``calls`` edges to related symbols.

    Phase 2: When no tests exist, suggest test files based on naming
    conventions (``tests/test_<module>.py``, ``test_<symbol>_*``, …).

    Returns ``(existing_tests, suggested_tests, test_ids)``.
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
            type="existing",
            test_file=node.file_path or "",
            test_name=node.name,
            reason=reason,
            confidence=confidence,
        ))
        test_ids.append(node.id)

    # Phase 1a: tested_by edges from entry points → tests
    for ep_id in entry_symbol_ids:
        for edge in store.get_outgoing_edges(ep_id):
            if edge.type == EdgeType.tested_by:
                test_node = store.get_node(edge.target)
                if test_node and test_node.type == NodeType.test:
                    _add_existing(
                        test_node,
                        reason=f"Tested_by edge — this test directly covers `{test_node.name}`.",
                        confidence=edge.confidence,
                    )

    # Phase 1b–1c: Scan all test nodes for name / call matches
    for node in store.all_nodes():
        if node.type != NodeType.test:
            continue
        if node.id in seen_test_ids:
            continue

        # 1b: Match by name — strip test_ prefix and check against entry names
        test_base = node.name
        if test_base.startswith("test_"):
            test_base = test_base[len("test_"):]
        # Split and try substrings: login_success → [login_success, login]
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

        # 1c: Match by calling task-related symbols
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

    # Phase 2: Suggestions when no tests found
    if not existing_tests:
        for ep in entry_points:
            file_path = ep.file_path or ""
            module_name = file_path.split("/")[-1].replace(".py", "") if file_path else ""
            test_path = f"tests/test_{module_name}.py"

            # tests/test_<module>.py
            suggested_tests.append(RelatedTest(
                type="suggested",
                test_file=test_path,
                test_name=f"test_{module_name}",
                reason=f"Recommended: create test module for {file_path or ep.name}",
                confidence=0.5,
            ))
            # Specific test function suggestions based on entry point name
            ep_name = ep.name.lower()
            for suffix in ("success", "valid", "basic", "happy_path", "error", "invalid",
                           "missing", "edge_case"):
                suggested_tests.append(RelatedTest(
                    type="suggested",
                    test_file=test_path,
                    test_name=f"test_{ep_name}_{suffix}",
                    reason=f"Recommended: test `{ep_name}` — {suffix.replace('_', ' ')} scenario.",
                    confidence=0.5,
                ))

    return existing_tests, suggested_tests, test_ids


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
    if not ranked and candidates:
        # Fallback: no keyword matched any symbol (e.g. "explain how authentication works"
        # where "authentication" doesn't appear in any node name). Return the top N
        # candidates with a default score so the pack isn't completely empty.
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
                    confidence_level=get_confidence_level(edge.confidence),
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
                    confidence_level=get_confidence_level(edge.confidence),
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
                    confidence_level=get_confidence_level(edge.confidence),
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
                    confidence_level=get_confidence_level(edge.confidence),
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
                    confidence_level=get_confidence_level(s.get("confidence", 0.0)),
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

    # ── Step 6.5: Discover model / config / store dependencies ──────────
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
        elif relation == "config_dependency":
            importance = Importance.high
            config_ids.append(sym_id)
        elif relation == "persistence_dependency":
            importance = Importance.high
            store_ids.append(sym_id)
        elif relation == "schema_dependency":
            importance = Importance.medium
            model_ids.append(sym_id)
        else:
            importance = Importance.medium
        related_symbols.append(RelatedSymbol(
            symbol_id=sym_id,
            relation=relation,
            distance=dist,
            direction="outgoing",
            reason=reason,
            importance=importance,
            confidence=confidence,
            confidence_level=get_confidence_level(confidence),
        ))

    # ── Step 7: Discover related tests ────────────────────────────────────
    existing_tests: list[RelatedTest] = []
    suggested_tests: list[RelatedTest] = []
    test_ids: list[str] = []
    if include_tests:
        existing_tests, suggested_tests, test_ids = _discover_related_tests(store, entry_points, related_ids)

        # Sync existing tests into related_symbols for context selection
        for rt in existing_tests:
            if rt.type != "existing":
                continue
            if rt.test_file not in {rs.symbol_id for rs in related_symbols}:
                related_symbols.append(RelatedSymbol(
                    symbol_id=rt.test_file,
                    relation="test",
                    distance=2,
                    direction="incoming",
                    reason=rt.reason,
                    importance=Importance.high,
                    confidence=rt.confidence,
                    confidence_level=get_confidence_level(rt.confidence),
                ))

    # ── Step 8: Select recommended context (with token budget) ────────────
    selector = ContextSelector(store, task_description, max_tokens)

    # Entry points always get critical priority — add them first
    ep_context: list[RecommendedContext] = []
    for i, ep in enumerate(entry_points):
        node = store.get_node(ep.symbol_id)
        if node:
            content = node.code_preview or ""
            loc = node.location
            ep_context.append(RecommendedContext(
                context_id=f"ctx_item_{i + 1:03d}",
                type="code_snippet",
                symbol_id=ep.symbol_id,
                file_path=ep.file_path,
                line_start=loc.line_start if loc else 0,
                line_end=loc.line_end if loc else 0,
                priority="critical",
                reason=ep.reason or "Main entry point for task",
                content=content,
                estimated_tokens=estimate_tokens(content),
                content_mode="full_source",
                context_score=ep.score,
            ))
            selector.budget.spend(estimate_tokens(content))

    # Run the selector for all related symbols
    sel_recommended, sel_optional = selector.select(entry_points, related_symbols)
    recommended_context = ep_context + sel_recommended
    optional_context = sel_optional

    # ── Step 9: Build reading plan ────────────────────────────────────────
    callee_ids = [rs.symbol_id for rs in related_symbols if rs.relation == "callee"]
    caller_ids = [rs.symbol_id for rs in related_symbols if rs.relation == "caller"]
    entry_ids = [ep.symbol_id for ep in entry_points]

    # Merge file-path-based config_ids with tag-based detection
    file_config_ids = [
        sid for sid in related_ids
        if sid not in set(entry_ids) and rplan.is_config_file(sid.split("::")[0])
    ]
    all_config_ids = list(dict.fromkeys(config_ids + file_config_ids))

    # Detect whether any entry point is a route handler
    has_route_handler = any(
        "route" in (store.get_node(ep.symbol_id).tags if store.get_node(ep.symbol_id) else [])
        for ep in entry_points
    )

    # Collect low-confidence symbol IDs for deferred reading plan placement
    low_conf_id_set: set[str] = {
        rs.symbol_id for rs in related_symbols if is_low_confidence(rs.confidence)
    }

    reading_plan = rplan.build_reading_plan(
        entry_point_ids=entry_ids,
        callee_ids=callee_ids,
        caller_ids=caller_ids,
        test_ids=test_ids,
        config_ids=all_config_ids,
        model_ids=model_ids,
        store_ids=store_ids,
        has_suggested_tests=bool(suggested_tests),
        has_route_handler=has_route_handler,
        max_steps=max_files + 4,
        low_confidence_ids=low_conf_id_set,
    )

    # ── Step 10: Build agent instructions ─────────────────────────────────
    warnings: list[str] = []

    # Collect low-confidence edges (< 0.60) for warnings
    low_conf_edges = [e for e in call_edges if is_low_confidence(e.confidence)]
    if low_conf_edges:
        edge_details = ", ".join(
            f"{e.source.split('::')[-1]}→{e.target.split('::')[-1]} ({e.confidence:.2f})"
            for e in low_conf_edges[:5]
        )
        warnings.append(
            f"{len(low_conf_edges)} edge(s) have confidence below 0.60 — "
            f"treat these relationships as weak signals: {edge_details}"
        )

    # Collect low-confidence related symbols
    low_conf_symbols = [rs for rs in related_symbols if is_low_confidence(rs.confidence)]
    if low_conf_symbols:
        sym_details = ", ".join(
            f"{rs.symbol_id.split('::')[-1]} ({rs.relation}, {rs.confidence:.2f})"
            for rs in low_conf_symbols[:5]
        )
        warnings.append(
            f"{len(low_conf_symbols)} related symbol(s) have low confidence — "
            f"verify manually before relying on them: {sym_details}"
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
        optional_context=optional_context,
        related_tests=existing_tests,
        suggested_tests=suggested_tests,
        reading_plan=reading_plan,
        agent_instructions=agent_instructions,
        exports=ExportsInfo(),
        token_budget=selector.budget.as_dict(),
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
