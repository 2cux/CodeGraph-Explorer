"""Impact analysis — determine what is affected by modifying a symbol.

PRD §19 — Impact analysis logic.
"""

from collections import deque

from codegraph.graph.confidence import get_confidence_level, is_low_confidence
from codegraph.graph.store import GraphStore
from codegraph.graph.models import EdgeType, NodeType

# Sensitive paths that indicate higher risk — PRD §19.3(3)
_SENSITIVE_KEYWORDS = [
    "auth", "password", "token", "payment", "permission",
    "delete", "admin", "credential", "secret", "login",
    "security", "cert", "encrypt", "session", "rbac",
]

# State mutation keywords — writing, persisting, or modifying data
_STATE_MUTATION_KEYWORDS = [
    "save", "write", "store", "persist", "create", "insert",
    "update", "set", "remove", "delete", "modify", "put",
    "patch", "commit", "flush", "sync", "upload",
]


def transitive_callers(
    store: GraphStore, node_id: str, depth: int
) -> list[tuple[str, int]]:
    """Traverse up the call chain to find all transitive callers.

    Returns ``(caller_id, distance)`` sorted by distance ascending.
    """
    seen: dict[str, int] = {node_id: 0}
    queue: deque[tuple[str, int]] = deque()
    queue.append((node_id, 0))

    while queue:
        current, dist = queue.popleft()
        if dist >= depth:
            continue
        for edge in store.get_incoming_edges(current):
            if edge.type == EdgeType.calls and edge.source not in seen:
                seen[edge.source] = dist + 1
                queue.append((edge.source, dist + 1))

    seen.pop(node_id, None)
    return sorted(seen.items(), key=lambda x: (x[1], x[0]))


def transitive_callees(
    store: GraphStore, node_id: str, depth: int
) -> list[tuple[str, int]]:
    """Traverse down the call chain to find all transitive callees.

    Returns ``(callee_id, distance)`` sorted by distance ascending.
    """
    seen: dict[str, int] = {node_id: 0}
    queue: deque[tuple[str, int]] = deque()
    queue.append((node_id, 0))

    while queue:
        current, dist = queue.popleft()
        if dist >= depth:
            continue
        for edge in store.get_outgoing_edges(current):
            if edge.type == EdgeType.calls and edge.target not in seen:
                seen[edge.target] = dist + 1
                queue.append((edge.target, dist + 1))

    seen.pop(node_id, None)
    return sorted(seen.items(), key=lambda x: (x[1], x[0]))


# ── Risk helpers ──────────────────────────────────────────────────────────


def _is_sensitive_path(file_path: str) -> bool:
    """Check if a file path contains sensitive keywords — PRD §19.3(3)."""
    lower = file_path.lower()
    return any(kw in lower for kw in _SENSITIVE_KEYWORDS)


def _is_public_api(file_path: str) -> bool:
    """Check if a symbol is part of a public API layer."""
    return "/api/" in file_path.lower()


def _is_same_module(id_a: str, id_b: str) -> bool:
    """Check if two node IDs belong to the same module.

    Node IDs ending with ``::symbol`` share the module prefix before ``::``.
    """
    mod_a = id_a.split("::")[0] if "::" in id_a else id_a
    mod_b = id_b.split("::")[0] if "::" in id_b else id_b
    return mod_a == mod_b


def _is_test_file(file_path: str) -> bool:
    """Check if a file path is a test file (heuristic)."""
    lower = file_path.lower()
    return "test" in lower


def _has_state_mutation(file_path: str) -> bool:
    """Check if a file path involves state mutation (data writes, persistence)."""
    lower = file_path.lower()
    return any(kw in lower for kw in _STATE_MUTATION_KEYWORDS)


def _assess_risk(
    store: GraphStore,
    node_id: str,
    center_node,
    callers: list[tuple[str, int]],
    callees: list[tuple[str, int]],
    max_distance: int,
    has_tests: bool,
    low_conf_count: int,
) -> tuple[str, list[str]]:
    """Rule-based risk assessment.

    Criteria per priority order:

    **low:**    Isolated utility / local function with no callers or callees.
    **medium:** Normal business function with limited callers.
    **high:**   Security-sensitive path (auth, payment, permission, data
                persistence), public API surface, or very broad callers (>5).
    **critical:** High-risk criteria PLUS no tests AND multiple callers
                  AND security-sensitive state mutation.
    """
    reasons: list[str] = []

    # Only count callable nodes (function, method, class, test) — skip
    # module/file/repository nodes that inflate the count.
    _callable_types = {NodeType.function, NodeType.method, NodeType.class_, NodeType.test}
    caller_count = sum(1 for cid, _ in callers
                       if (n := store.get_node(cid)) and n.type in _callable_types)
    callee_count = sum(1 for cid, _ in callees
                       if (n := store.get_node(cid)) and n.type in _callable_types)
    file_path = center_node.file_path if center_node else ""
    is_sensitive = _is_sensitive_path(file_path)
    is_api = _is_public_api(file_path)
    has_state_mutation = _has_state_mutation(file_path)

    # Route handler metadata — always a public API surface
    route_info = center_node.metadata.get("route") if center_node and center_node.metadata else None
    is_route = bool(route_info) or ("route" in (center_node.tags if center_node else []))
    if is_route:
        is_api = True
        rfw = route_info.get("framework", "") if route_info else ""
        rmethod = route_info.get("method", "") if route_info else ""
        rpath = route_info.get("path", "") if route_info else ""
        reasons.append(f"HTTP route handler ({rfw} {rmethod} {rpath}) — changes affect the external API contract.")
        # Route path sensitivity: auth, payment, admin, delete endpoints
        if rpath and _is_sensitive_path(rpath):
            is_sensitive = True
            reasons.append(f"Route path `{rpath}` touches a security-sensitive endpoint.")

    # Build evidence
    if is_sensitive and not is_route:
        reasons.append("Security-sensitive path — involves auth, credentials, or security logic.")
    if is_api and not is_route:
        reasons.append("Public API route — changes affect external interfaces.")
    if has_state_mutation:
        reasons.append("State mutation — this code writes or persists data.")
    if caller_count > 0:
        reasons.append(f"{caller_count} upstream caller(s) may be affected.")
    if not has_tests:
        reasons.append("No related tests detected — changes may lack regression coverage.")
    if low_conf_count > 0:
        reasons.append(f"{low_conf_count} edge(s) have low confidence — relationships may be incomplete.")

    # Rule-based level (first match wins)
    # ── critical ──────────────────────────────────────────────────────
    if is_sensitive and not has_tests and caller_count >= 3 and has_state_mutation:
        reasons.append("SECURITY-SENSITIVE, UNTESTED, STATE-MUTATING, MULTIPLE CALLERS — high regression risk.")
        return "critical", reasons

    # ── high ─────────────────────────────────────────────────────────
    if is_sensitive:
        return "high", reasons or ["Security-sensitive code path."]
    if is_api:
        return "high", reasons or ["Public API surface."]
    if caller_count >= 5:
        reasons.append(f"Broad upstream impact — {caller_count} callers.")
        return "high", reasons

    # ── medium ───────────────────────────────────────────────────────
    if caller_count > 0 or callee_count > 0:
        return "medium", reasons or ["Business function with callers or callees."]

    # ── low ──────────────────────────────────────────────────────────
    return "low", ["Isolated symbol — no callers or callees detected."]


def _build_recommendations(
    node_id: str,
    center_node,
    callers: list[tuple[str, int]],
    callees: list[tuple[str, int]],
    affected_files: dict[str, dict],
    has_tests: bool,
    file_path: str,
) -> list[str]:
    """Generate a recommended check/reading order — PRD §11.5."""
    order: list[str] = []

    # Step 1: Read the changed symbol
    order.append(
        f"Read the definition of '{node_id}' to understand current behavior."
    )

    # Step 2: Read upstream callers (high-priority)
    if callers:
        near_callers = [cid for cid, d in callers if d <= 1]
        if near_callers:
            caller_list = ", ".join(near_callers[:3])
            order.append(
                f"Review direct callers: {caller_list} — "
                f"these invoke the changed symbol."
            )
        if len(callers) > 3:
            order.append(
                f"Check remaining {len(callers) - 3} caller(s) for cascading effects."
            )

    # Step 3: Read downstream callees (dependencies)
    if callees:
        near_callees = [cid for cid, d in callees if d <= 1]
        if near_callees:
            callee_list = ", ".join(near_callees[:3])
            order.append(
                f"Inspect direct callees: {callee_list} — "
                f"these are called by the changed symbol."
            )

    # Step 4: Sensitive path warning
    if file_path and _is_sensitive_path(file_path):
        order.append(
            "Exercise caution — changes touch a security-sensitive code path."
        )

    # Step 5: Tests
    if has_tests:
        order.append("Update related tests before deploying changes.")
    else:
        order.append("Consider adding tests to cover the change.")

    # Step 6: High-priority files to modify
    high_priority_files = [
        f for f in affected_files.values() if f.get("priority") == "high"
    ]
    if high_priority_files:
        file_list = ", ".join(f["file_path"] for f in high_priority_files[:3])
        order.append(f"Prioritize changes in: {file_list}.")

    return order


def _add_model_config_store_impact(
    store: GraphStore,
    node_id: str,
    center_node,
    affected_symbols: list[dict],
    affected_files: dict[str, dict],
) -> None:
    """Find model/config/store classes imported by the center node's file.

    Adds them as affected symbols with ``shared_model`` or ``config_dependency``
    impact types.
    """
    if not center_node or not center_node.file_path:
        return

    file_id = center_node.file_path
    seen: set[str] = set()

    # Build qualified_name → class node lookup
    qual_to_class: dict[str, GraphNode] = {}
    for node in store.all_nodes():
        if node.type == NodeType.class_ and node.qualified_name:
            qual_to_class[node.qualified_name] = node

    for edge in store.get_outgoing_edges(file_id):
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

        def _entry(sid: str, reason: str, impact_type: str) -> dict:
            n = store.get_node(sid)
            conf = 0.85
            return {
                "symbol_id": sid,
                "name": n.name if n else sid,
                "type": n.type.value if n and hasattr(n.type, "value") else "unknown",
                "file_path": n.file_path if n else "",
                "reason": reason,
                "impact_type": impact_type,
                "distance": 1,
                "confidence": conf,
                "confidence_level": get_confidence_level(conf),
            }

        if "model" in tags and "config" not in tags:
            seen.add(class_node.id)
            affected_symbols.append(_entry(
                class_node.id,
                f"Data model `{class_name}` — modifying `{center_node.name}` may require field additions or schema changes.",
                "shared_model",
            ))
            if class_node.file_path:
                _add_file(affected_files, class_node.file_path,
                          f"Data model file — changes may require field updates.", "high")

        elif "config" in tags or "settings" in tags:
            seen.add(class_node.id)
            affected_symbols.append(_entry(
                class_node.id,
                f"Configuration `{class_name}` — changes to `{center_node.name}` may need new config fields or settings.",
                "config_dependency",
            ))
            if class_node.file_path:
                _add_file(affected_files, class_node.file_path,
                          f"Configuration file — feature changes may need config updates.", "high")

        elif "store" in tags or "persistence" in tags:
            seen.add(class_node.id)
            affected_symbols.append(_entry(
                class_node.id,
                f"Persistence `{class_name}` — behavior changes in `{center_node.name}` may require store or repository updates.",
                "upstream_caller",
            ))
            if class_node.file_path:
                _add_file(affected_files, class_node.file_path,
                          f"Persistence layer file — data read/write changes may be needed.", "high")


# ── Public API ─────────────────────────────────────────────────────────────


def analyze_impact(
    store: GraphStore, node_id: str, depth: int = 2
) -> dict:
    """Analyze the impact surface of modifying a symbol up to given depth.

    Returns a dict with keys:
      changed_symbol       — the node ID of the symbol being changed
      changed_symbol_type  — type of the changed symbol
      affected_symbols     — list of affected symbol dicts
      affected_files       — list of affected file dicts
      related_tests        — list of dicts with test info (existing tests + gaps)
      risk                 — dict with ``level``, ``score``, and ``reasons``
      recommendations      — ordered check-step strings (read this, update that…)
      warnings             — list of warning strings (low-confidence edges, …)
    """
    center = store.get_node(node_id)
    if not center:
        return {
            "changed_symbol": node_id,
            "affected_symbols": [],
            "affected_files": [],
            "related_tests": [],
            "risk": {"level": "unknown", "reasons": ["Symbol not found in index."]},
            "recommendations": [],
            "warnings": ["Symbol not found in index."],
        }

    callers = transitive_callers(store, node_id, depth)
    callees = transitive_callees(store, node_id, depth)

    affected_symbols: list[dict] = []
    affected_files: dict[str, dict] = {}
    max_dist = 0
    low_conf_count = 0
    has_tests = False

    # Count low-confidence edges connected to the center
    for edge in store.get_outgoing_edges(node_id):
        if is_low_confidence(edge.confidence):
            low_conf_count += 1
    for edge in store.get_incoming_edges(node_id):
        if is_low_confidence(edge.confidence):
            low_conf_count += 1

    # Helper to build symbol dicts with common fields
    def _symbol_entry(
        symbol_id: str,
        reason: str,
        impact_type: str,
        distance: int,
        confidence: float,
        node=None,
    ) -> dict:
        n = node or store.get_node(symbol_id)
        return {
            "symbol_id": symbol_id,
            "name": n.name if n else symbol_id,
            "type": (
                n.type.value
                if n and hasattr(n.type, "value")
                else (str(n.type) if n else "unknown")
            ),
            "file_path": n.file_path if n else "",
            "reason": reason,
            "impact_type": impact_type,
            "distance": distance,
            "confidence": confidence,
            "confidence_level": get_confidence_level(confidence),
        }

    # Direct definition of the changed symbol
    affected_symbols.append(_symbol_entry(
        symbol_id=node_id,
        reason="Direct definition — the symbol being modified.",
        impact_type="direct_definition",
        distance=0,
        confidence=1.0,
        node=center,
    ))

    if center.file_path:
        _add_file(affected_files, center.file_path,
                  "Direct definition in this file.", "high")

    # Upstream callers
    for caller_id, dist in callers:
        node = store.get_node(caller_id)
        max_dist = max(max_dist, dist)
        affected_symbols.append(_symbol_entry(
            symbol_id=caller_id,
            reason=f"Calls the changed symbol (distance {dist}).",
            impact_type="upstream_caller",
            distance=dist,
            confidence=max(0.0, 1.0 - dist * 0.15),
            node=node,
        ))
        if node and node.file_path:
            _add_file(affected_files, node.file_path,
                      f"Upstream caller at distance {dist}.",
                      "high" if dist <= 1 else "medium")

    # Downstream callees
    for callee_id, dist in callees:
        node = store.get_node(callee_id)
        max_dist = max(max_dist, dist)
        affected_symbols.append(_symbol_entry(
            symbol_id=callee_id,
            reason=f"Called by the changed symbol (distance {dist}).",
            impact_type="downstream_call",
            distance=dist,
            confidence=max(0.0, 1.0 - dist * 0.15),
            node=node,
        ))
        if node and node.file_path:
            _add_file(affected_files, node.file_path,
                      f"Downstream callee at distance {dist}.", "medium")

    # ── Model / config / store dependencies via imports ─────────────────
    _add_model_config_store_impact(store, node_id, center, affected_symbols, affected_files)

    # ── Tests: collect related tests via tested_by and calls edges ──────
    related_tests: list[dict] = []
    has_tests = False
    seen_test_ids: set[str] = set()

    # Direct tested_by edges (target --tested_by--> test)
    for edge in store.get_outgoing_edges(node_id):
        if edge.type == EdgeType.tested_by:
            test_node = store.get_node(edge.target)
            if test_node and test_node.id not in seen_test_ids:
                has_tests = True
                seen_test_ids.add(test_node.id)
                related_tests.append({
                    "symbol_id": test_node.id,
                    "name": test_node.name,
                    "file_path": test_node.file_path or "",
                    "reason": "Tested_by edge — this test directly covers the changed symbol.",
                    "confidence": edge.confidence,
                    "type": "existing",
                })
                affected_symbols.append(_symbol_entry(
                    symbol_id=test_node.id,
                    reason="Test coverage — this test exercises the changed symbol.",
                    impact_type="test_coverage",
                    distance=1,
                    confidence=edge.confidence,
                    node=test_node,
                ))
                if test_node.file_path:
                    _add_file(affected_files, test_node.file_path,
                              "Test file covering this symbol.", "high")

    # Tests that directly call the changed symbol (calls edge from test → target)
    for edge in store.get_incoming_edges(node_id):
        src_node = store.get_node(edge.source)
        if src_node and src_node.type == NodeType.test and edge.type == EdgeType.calls:
            if src_node.id not in seen_test_ids:
                has_tests = True
                seen_test_ids.add(src_node.id)
                related_tests.append({
                    "symbol_id": src_node.id,
                    "name": src_node.name,
                    "file_path": src_node.file_path or "",
                    "reason": "Test calls the changed symbol directly.",
                    "confidence": edge.confidence,
                    "type": "existing",
                })
                affected_symbols.append(_symbol_entry(
                    symbol_id=edge.source,
                    reason="Test coverage — this test exercises the changed symbol.",
                    impact_type="test_coverage",
                    distance=1,
                    confidence=edge.confidence,
                    node=src_node,
                ))
                if src_node.file_path:
                    _add_file(affected_files, src_node.file_path,
                              "Test file covering this symbol.", "high")
        elif edge.type == EdgeType.references:
            ref_node = store.get_node(edge.source)
            if ref_node and ref_node.file_path:
                _add_file(affected_files, ref_node.file_path,
                          "References this symbol.", "medium")

    # Also check test files among callers (indirect test coverage)
    if not has_tests:
        for caller_id, _ in callers:
            caller_node = store.get_node(caller_id)
            if caller_node and caller_node.type == NodeType.test:
                has_tests = True
                seen_test_ids.add(caller_id)
                related_tests.append({
                    "symbol_id": caller_id,
                    "name": caller_node.name,
                    "file_path": caller_node.file_path or "",
                    "reason": "Test is an upstream caller of the changed symbol.",
                    "confidence": 0.6,
                    "type": "existing",
                })
                break
            if caller_node and caller_node.file_path and _is_test_file(caller_node.file_path):
                has_tests = True
                break

    # Risk assessment
    level, reasons = _assess_risk(
        store, node_id, center, callers, callees,
        max_dist, has_tests, low_conf_count,
    )

    # Recommendations
    recommendations = _build_recommendations(
        node_id, center, callers, callees,
        affected_files, has_tests, center.file_path or "",
    )

    # Warnings
    warnings: list[str] = []
    if low_conf_count > 0:
        warnings.append(
            f"{low_conf_count} edge(s) have confidence below 0.6 — "
            "treat these relationships as weak signals."
        )

    return {
        "changed_symbol": node_id,
        "changed_symbol_type": (
            center.type.value
            if hasattr(center.type, "value")
            else str(center.type)
        ),
        "affected_symbols": affected_symbols,
        "affected_files": list(affected_files.values()),
        "related_tests": related_tests,
        "risk": {"level": level, "reasons": reasons},
        "recommendations": recommendations,
        "warnings": warnings,
    }


def _add_file(
    files: dict[str, dict],
    file_path: str,
    reason: str,
    priority: str = "medium",
) -> None:
    """Add or update an affected file entry.

    When a file is added with ``priority="high"`` it upgrades any existing
    entry regardless of previous priority.
    """
    if file_path not in files:
        files[file_path] = {
            "file_path": file_path,
            "reason": reason,
            "priority": priority,
        }
    elif priority == "high" and files[file_path]["priority"] != "high":
        files[file_path]["priority"] = "high"
        files[file_path]["reason"] = reason
