"""Impact analysis — determine what is affected by modifying a symbol."""

from collections import deque

from codegraph.graph.store import GraphStore
from codegraph.graph.models import EdgeType, NodeType


def transitive_callers(
    store: GraphStore, node_id: str, depth: int
) -> list[tuple[str, int]]:
    """Traverse up the call chain to find all transitive callers.

    Returns ``(caller_id, distance)`` sorted by distance ascending.
    """
    seen: dict[str, int] = {node_id: 0}  # mark center as visited
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

    return sorted(seen.items(), key=lambda x: (x[1], x[0]))


def _risk_level(
    caller_count: int, callee_count: int, max_distance: int
) -> tuple[str, list[str]]:
    """Determine risk level based on impact breadth and depth."""
    reasons: list[str] = []

    if caller_count == 0 and callee_count == 0:
        return "low", ["No callers or callees detected — isolated symbol."]

    if caller_count > 0:
        reasons.append(f"Affects {caller_count} upstream caller(s).")

    if callee_count > 0:
        reasons.append(f"Depends on {callee_count} downstream callee(s).")

    if caller_count == 0:
        pass  # no callers = no downstream risk

    if caller_count >= 10:
        return "critical", reasons + ["Widespread impact — 10+ callers."]

    if caller_count >= 5 or max_distance >= 4:
        return "high", reasons + [f"Significant reach (depth {max_distance})."]

    if caller_count >= 2 or max_distance >= 2:
        return "medium", reasons

    return "low", reasons


def analyze_impact(
    store: GraphStore, node_id: str, depth: int = 2
) -> dict:
    """Analyze the impact surface of modifying a symbol up to given depth.

    Returns a dict with keys:
      affected_symbols  — list of dicts
      affected_files    — list of dicts
      risk              — dict with level and reasons
    """
    center = store.get_node(node_id)
    if not center:
        return {
            "changed_symbol": node_id,
            "affected_symbols": [],
            "affected_files": [],
            "risk": {"level": "unknown", "reasons": ["Symbol not found."]},
        }

    callers = transitive_callers(store, node_id, depth)
    callees = transitive_callees(store, node_id, depth)

    affected_symbols: list[dict] = []
    affected_files: dict[str, dict] = {}
    max_dist = 0

    # Direct definition of the changed symbol
    affected_symbols.append({
        "symbol_id": node_id,
        "reason": "Direct definition — the symbol being modified.",
        "impact_type": "direct_definition",
        "distance": 0,
        "confidence": 1.0,
    })

    if center.file_path:
        _add_file(affected_files, center.file_path, "Direct definition in this file.", "high")

    # Upstream callers
    for caller_id, dist in callers:
        node = store.get_node(caller_id)
        max_dist = max(max_dist, dist)
        affected_symbols.append({
            "symbol_id": caller_id,
            "reason": f"Calls the changed symbol (distance {dist}).",
            "impact_type": "upstream_caller",
            "distance": dist,
            "confidence": max(0.0, 1.0 - dist * 0.15),
        })
        if node and node.file_path:
            _add_file(affected_files, node.file_path, f"Upstream caller at distance {dist}.", "medium" if dist > 1 else "high")

    # Downstream callees
    for callee_id, dist in callees:
        node = store.get_node(callee_id)
        max_dist = max(max_dist, dist)
        affected_symbols.append({
            "symbol_id": callee_id,
            "reason": f"Called by the changed symbol (distance {dist}).",
            "impact_type": "downstream_call",
            "distance": dist,
            "confidence": max(0.0, 1.0 - dist * 0.15),
        })
        if node and node.file_path:
            _add_file(affected_files, node.file_path, f"Downstream callee at distance {dist}.", "medium")

    # Tests referencing the changed symbol
    for edge in store.get_incoming_edges(node_id):
        src_node = store.get_node(edge.source)
        if src_node and src_node.type == NodeType.test:
            affected_symbols.append({
                "symbol_id": edge.source,
                "reason": "Test coverage — this test exercises the changed symbol.",
                "impact_type": "test_coverage",
                "distance": 1,
                "confidence": 0.8,
            })
            if src_node.file_path:
                _add_file(affected_files, src_node.file_path, "Test file covering this symbol.", "high")
        elif edge.type == EdgeType.references:
            ref_node = store.get_node(edge.source)
            if ref_node and ref_node.file_path:
                _add_file(affected_files, ref_node.file_path, "References this symbol.", "medium")

    # Risk assessment
    level, reasons = _risk_level(len(callers), len(callees), max_dist)

    return {
        "changed_symbol": node_id,
        "affected_symbols": affected_symbols,
        "affected_files": list(affected_files.values()),
        "risk": {"level": level, "reasons": reasons},
    }


def _add_file(
    files: dict[str, dict],
    file_path: str,
    reason: str,
    priority: str = "medium",
) -> None:
    """Add or update an affected file entry."""
    if file_path not in files:
        files[file_path] = {
            "file_path": file_path,
            "reason": reason,
            "priority": priority,
        }
    elif priority == "high" and files[file_path]["priority"] != "high":
        files[file_path]["priority"] = "high"
        files[file_path]["reason"] = reason
