"""Impact analysis — determine what is affected by modifying a symbol.

PRD §19 — Impact analysis logic.
"""

from collections import deque

from codegraph.graph.store import GraphStore
from codegraph.graph.models import EdgeType, NodeType

# Sensitive paths that indicate higher risk — PRD §19.3(3)
_SENSITIVE_KEYWORDS = [
    "auth", "password", "token", "payment", "permission",
    "delete", "admin", "credential", "secret", "login",
    "security", "cert", "encrypt", "session", "rbac",
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
    """Comprehensive risk assessment — PRD §19.3.

    Factors considered:
      1. Number of callers (breadth of upstream impact)
      2. Number of callees (depth of downstream dependency)
      3. Sensitive path (auth / payment / permission / delete …)
      4. Public API exposure
      5. Test coverage (or lack thereof)
      6. Cross-module reach
      7. Low-confidence edges (analysis uncertainty)
      8. Import count (how many places import this symbol)
      9. Call-chain depth (how far effects propagate)
    """
    reasons: list[str] = []
    score = 0.0

    caller_count = len(callers)
    callee_count = len(callees)

    # Factor 1: Caller count
    if caller_count >= 10:
        score += 3.0
        reasons.append(f"Widespread impact — {caller_count} upstream callers.")
    elif caller_count >= 5:
        score += 2.0
        reasons.append(f"Significant impact — {caller_count} upstream callers.")
    elif caller_count >= 2:
        score += 1.0
        reasons.append(f"Affects {caller_count} upstream callers.")
    elif caller_count > 0:
        score += 0.5
        reasons.append(f"Affects {caller_count} upstream caller(s).")

    # Factor 2: Callee count
    if callee_count >= 10:
        score += 2.0
        reasons.append(f"Deep dependency chain — {callee_count} downstream callees.")
    elif callee_count >= 5:
        score += 1.5
        reasons.append(f"Moderate dependency chain — {callee_count} downstream callees.")
    elif callee_count >= 2:
        score += 1.0
        reasons.append(f"Depends on {callee_count} downstream callees.")
    elif callee_count > 0:
        score += 0.5

    # Factor 3: Sensitive path
    file_path = center_node.file_path if center_node else ""
    if _is_sensitive_path(file_path):
        score += 2.0
        reasons.append("Sensitive code path — changes may affect security-related logic.")
    if _is_public_api(file_path):
        score += 1.5
        reasons.append("Public API surface — changes affect external interfaces.")

    # Factor 4: Test coverage (no tests = higher risk)
    if has_tests:
        reasons.append("Related tests found — update them alongside changes.")
        score -= 0.5
    else:
        score += 1.0
        reasons.append("No related tests detected — changes may lack regression coverage.")

    # Factor 5: Cross-module impact
    if caller_count > 0 or callee_count > 0:
        all_related = [cid for cid, _ in callers] + [cid for cid, _ in callees]
        cross_module = sum(1 for cid in all_related if not _is_same_module(node_id, cid))
        if cross_module >= 3:
            score += 1.5
            reasons.append(f"Cross-module impact — affects {cross_module} symbols in different modules.")
        elif cross_module >= 1:
            score += 0.5

    # Factor 6: Low-confidence edges
    if low_conf_count >= 3:
        score += 1.5
        reasons.append(
            f"Analysis uncertainty — {low_conf_count} low-confidence "
            f"edges may hide additional impact."
        )
    elif low_conf_count >= 1:
        score += 0.5
        reasons.append(
            f"{low_conf_count} low-confidence edge(s) detected — "
            f"some relationships may be incomplete."
        )

    # Factor 7: Import count
    incoming_imports = 0
    for edge in store.get_incoming_edges(node_id):
        if edge.type == EdgeType.imports:
            incoming_imports += 1
    if incoming_imports >= 3:
        score += 1.0
        reasons.append(f"Imported by {incoming_imports} locations — widely referenced.")
    elif incoming_imports >= 1:
        score += 0.3

    # Factor 8: Depth / reach
    if max_distance >= 4:
        score += 1.0
        reasons.append(
            f"Deep call chain (depth {max_distance}) — "
            f"transitive effects may reach far."
        )
    elif max_distance >= 3:
        score += 0.5

    if caller_count == 0 and callee_count == 0 and not file_path:
        return "low", ["No callers or callees detected — isolated symbol."]

    # Determine level from score
    if score >= 5.0:
        return "critical", reasons
    elif score >= 3.0:
        return "high", reasons
    elif score >= 1.5:
        return "medium", reasons
    else:
        return "low", reasons


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
        if edge.confidence < 0.6:
            low_conf_count += 1
    for edge in store.get_incoming_edges(node_id):
        if edge.confidence < 0.6:
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

    # Tests and references touching the changed symbol
    for edge in store.get_incoming_edges(node_id):
        src_node = store.get_node(edge.source)
        if src_node and src_node.type == NodeType.test:
            has_tests = True
            affected_symbols.append(_symbol_entry(
                symbol_id=edge.source,
                reason="Test coverage — this test exercises the changed symbol.",
                impact_type="test_coverage",
                distance=1,
                confidence=0.8,
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
