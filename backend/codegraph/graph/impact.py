"""Impact analysis — determine what is affected by modifying a symbol.

Returns confirmed vs possible impact, separated by confidence, with
upstream/downstream/test/external items clearly labeled.
"""

from collections import deque
from typing import Any

from codegraph.graph.confidence import get_confidence_level, is_low_confidence
from codegraph.graph.store import GraphStore
from codegraph.graph.models import EdgeType, NodeType, Resolution, GraphEdge

# ── Resolution tier helpers ─────────────────────────────────────────────────

# Resolutions that produce confirmed edges (import-based, same-file, etc.)
_CONFIRMED_RESOLUTIONS: set[Resolution] = {
    Resolution.same_file_exact,
    Resolution.self_method_resolved,
    Resolution.class_method_resolved,
    Resolution.imported_function_exact,
    Resolution.imported_function_alias,
    Resolution.imported_module_attribute,
    Resolution.relative_import_resolved,
    Resolution.import_resolved,
    Resolution.parameter_type_hint_resolved,
    Resolution.local_instance_resolved,
    Resolution.module_instance_resolved,
    Resolution.constructor_call_resolved,
    Resolution.self_attribute_instance_resolved,
    Resolution.type_hint_resolved,
    Resolution.exact_ast_match,
    Resolution.fastapi_route_decorator,
    Resolution.flask_route_decorator,
    Resolution.framework_route_resolved,
}

# Resolutions that are possible / low-confidence candidates
_POSSIBLE_RESOLUTIONS: set[Resolution] = {
    Resolution.name_match_candidate,
    Resolution.filename_heuristic,
    Resolution.docstring_reference,
    Resolution.test_name_heuristic,
    Resolution.test_file_heuristic,
    Resolution.suggested_test,
    Resolution.attribute_guess,
    Resolution.same_module_fallback,
    Resolution.django_view_heuristic,
}

# Resolutions that are unresolved / external
_UNRESOLVED_RESOLUTIONS: set[Resolution] = {
    Resolution.dynamic_getattr,
    Resolution.reflection_call,
    Resolution.unknown_external,
    Resolution.decorator_unknown,
    Resolution.import_not_found,
    Resolution.external_symbol,
    Resolution.unresolved,
}


def is_confirmed_resolution(resolution: Resolution) -> bool:
    """True if the resolution is in the confirmed tier."""
    return resolution in _CONFIRMED_RESOLUTIONS


def is_possible_resolution(resolution: Resolution) -> bool:
    """True if the resolution is in the possible / low-confidence tier."""
    return resolution in _POSSIBLE_RESOLUTIONS


def is_unresolved_resolution(resolution: Resolution) -> bool:
    """True if the resolution is in the unresolved / external tier."""
    return resolution in _UNRESOLVED_RESOLUTIONS


def classify_edge_resolution(resolution: Resolution) -> str:
    """Classify a resolution into 'confirmed', 'possible', or 'unresolved'."""
    if resolution in _CONFIRMED_RESOLUTIONS:
        return "confirmed"
    if resolution in _POSSIBLE_RESOLUTIONS:
        return "possible"
    if resolution in _UNRESOLVED_RESOLUTIONS:
        return "unresolved"
    return "unresolved"

# Sensitive paths that indicate higher risk
_SENSITIVE_KEYWORDS = [
    "auth", "password", "token", "payment", "permission",
    "delete", "admin", "credential", "secret", "login",
    "security", "cert", "encrypt", "session", "rbac",
]

# State mutation keywords
_STATE_MUTATION_KEYWORDS = [
    "save", "write", "store", "persist", "create", "insert",
    "update", "set", "remove", "delete", "modify", "put",
    "patch", "commit", "flush", "sync", "upload",
]


def transitive_callers(
    store: GraphStore, node_id: str, depth: int
) -> list[tuple[str, int, float]]:
    """Traverse up the call chain finding transitive callers.

    Returns ``(caller_id, distance, edge_confidence)`` sorted by distance.
    Skips edges with unresolved-tier resolutions (name_match_candidate, etc.).
    """
    seen: dict[str, int] = {node_id: 0}
    # Track the edge confidence that led to each node
    node_confidence: dict[str, float] = {}
    queue: deque[tuple[str, int]] = deque()
    queue.append((node_id, 0))

    while queue:
        current, dist = queue.popleft()
        if dist >= depth:
            continue
        for edge in store.get_incoming_edges(current):
            if edge.type == EdgeType.calls and edge.source not in seen:
                # Skip unresolved-tier edges — they must not be traversed
                edge_res = edge.metadata.resolution if edge.metadata else None
                if edge_res is not None and is_unresolved_resolution(edge_res):
                    continue
                seen[edge.source] = dist + 1
                node_confidence[edge.source] = edge.confidence
                queue.append((edge.source, dist + 1))

    seen.pop(node_id, None)
    result = [(cid, d, node_confidence.get(cid, 1.0)) for cid, d in seen.items()]
    return sorted(result, key=lambda x: (x[1], x[0]))


def transitive_callees(
    store: GraphStore, node_id: str, depth: int
) -> list[tuple[str, int, float]]:
    """Traverse down the call chain finding transitive callees.

    Returns ``(callee_id, distance, edge_confidence)`` sorted by distance.
    Skips edges with unresolved-tier resolutions (name_match_candidate, etc.).
    """
    seen: dict[str, int] = {node_id: 0}
    node_confidence: dict[str, float] = {}
    queue: deque[tuple[str, int]] = deque()
    queue.append((node_id, 0))

    while queue:
        current, dist = queue.popleft()
        if dist >= depth:
            continue
        for edge in store.get_outgoing_edges(current):
            if edge.type == EdgeType.calls and edge.target not in seen:
                # Skip unresolved-tier edges — they must not be traversed
                edge_res = edge.metadata.resolution if edge.metadata else None
                if edge_res is not None and is_unresolved_resolution(edge_res):
                    continue
                seen[edge.target] = dist + 1
                node_confidence[edge.target] = edge.confidence
                queue.append((edge.target, dist + 1))

    seen.pop(node_id, None)
    result = [(cid, d, node_confidence.get(cid, 1.0)) for cid, d in seen.items()]
    return sorted(result, key=lambda x: (x[1], x[0]))


# ── Risk helpers ──────────────────────────────────────────────────────────


def _is_sensitive_path(file_path: str) -> bool:
    lower = file_path.lower()
    return any(kw in lower for kw in _SENSITIVE_KEYWORDS)


def _is_public_api(file_path: str) -> bool:
    return "/api/" in file_path.lower()


def _has_state_mutation(file_path: str) -> bool:
    lower = file_path.lower()
    return any(kw in lower for kw in _STATE_MUTATION_KEYWORDS)


def _assess_risk(
    store: GraphStore,
    node_id: str,
    center_node,
    callers: list[tuple[str, int, float]],
    callees: list[tuple[str, int, float]],
    has_tests: bool,
    low_conf_count: int,
) -> tuple[str, list[str]]:
    """Rule-based risk assessment — fact-based, no action advice.

    Levels:
      low:      Isolated utility function with no/few callers
      medium:   Normal business function with limited callers
      high:     Security-sensitive, public API, or broad impact
      critical: Security-sensitive + untested + state-mutating + many callers
      unknown:  Insufficient data
    """
    reasons: list[str] = []

    _callable_types = {NodeType.function, NodeType.method, NodeType.class_, NodeType.test}
    caller_count = sum(1 for cid, _, _ in callers
                       if (n := store.get_node(cid)) and n.type in _callable_types)
    callee_count = sum(1 for cid, _, _ in callees
                       if (n := store.get_node(cid)) and n.type in _callable_types)
    file_path = center_node.file_path if center_node else ""
    is_sensitive = _is_sensitive_path(file_path)
    is_api = _is_public_api(file_path)
    has_state_mutation = _has_state_mutation(file_path)

    # Route handler metadata
    route_info = center_node.metadata.get("route") if center_node and center_node.metadata else None
    is_route = bool(route_info) or ("route" in (center_node.tags if center_node else []))
    if is_route:
        is_api = True
        rfw = route_info.get("framework", "") if route_info else ""
        rmethod = route_info.get("method", "") if route_info else ""
        rpath = route_info.get("path", "") if route_info else ""
        reasons.append(f"HTTP route handler ({rfw} {rmethod} {rpath}) — changes affect the external API contract.")
        if rpath and _is_sensitive_path(rpath):
            is_sensitive = True
            reasons.append(f"Route path touches a security-sensitive endpoint: {rpath}")

    if is_sensitive and not is_route:
        reasons.append("Security-sensitive path — involves auth, credentials, or security logic.")
    if is_api and not is_route:
        reasons.append("Public API surface — changes affect external interfaces.")
    if has_state_mutation:
        reasons.append("State mutation — code writes or persists data.")
    if caller_count > 0:
        reasons.append(f"{caller_count} upstream caller(s) may be affected.")
    if callee_count > 0:
        reasons.append(f"{callee_count} downstream callee(s) may be affected.")
    if not has_tests:
        reasons.append("No related tests detected.")
    if low_conf_count > 0:
        reasons.append(f"{low_conf_count} low-confidence edge(s) — some relationships may be incomplete.")

    # Risk level (first match wins)
    if is_sensitive and not has_tests and caller_count >= 3 and has_state_mutation:
        return "critical", reasons + ["Security-sensitive, untested, state-mutating, multiple callers."]
    if is_sensitive:
        return "high", reasons
    if is_api:
        return "high", reasons
    if caller_count >= 5:
        return "high", reasons
    if caller_count > 0 or callee_count > 0:
        return "medium", reasons
    return "low", reasons or ["Isolated symbol — no detected callers or callees."]


# ── Public API ─────────────────────────────────────────────────────────────


def analyze_impact(
    store: GraphStore, node_id: str, depth: int = 2, min_confidence: float = 0.6
) -> dict:
    """Analyze the impact surface of modifying a symbol.

    Returns a dict with keys:
      risk                    — dict with ``level`` and ``reasons``
      confirmed_impact        — dict with ``symbols`` and ``files`` (confidence >= min_confidence)
      possible_impact         — dict with ``symbols`` and ``files`` (confidence < min_confidence)
      upstream_callers        — list of dicts (caller symbol info + edge evidence)
      downstream_callees      — list of dicts (callee symbol info + edge evidence)
      related_tests           — list of dicts with test info
      external_or_unresolved  — list of dicts for external/unresolved references
    """
    center = store.get_node(node_id)
    if not center:
        return {
            "risk": {"level": "unknown", "reasons": ["Symbol not found in index."]},
            "confirmed_impact": {"symbols": [], "files": []},
            "possible_impact": {"symbols": [], "files": []},
            "upstream_callers": [],
            "downstream_callees": [],
            "related_tests": [],
            "external_or_unresolved": [],
        }

    callers = transitive_callers(store, node_id, depth)
    callees = transitive_callees(store, node_id, depth)

    # ── Class-level aggregation: if this is a class with no direct callers,
    #     aggregate callers/callees from all its methods ────────────────────
    is_class = center.type == NodeType.class_
    if is_class and not callers and not callees:
        # Find methods of this class (nodes whose ID starts with class_id + ".")
        class_prefix = node_id + "."
        method_ids = [
            n.id for n in store.all_nodes()
            if n.id.startswith(class_prefix) and n.type == NodeType.method
        ]
        for mid in method_ids:
            for caller_id, dist, conf in transitive_callers(store, mid, depth):
                if caller_id not in {c[0] for c in callers}:
                    callers.append((caller_id, min(depth, dist + 1), conf))
            for callee_id, dist, conf in transitive_callees(store, mid, depth):
                if callee_id not in {c[0] for c in callees}:
                    callees.append((callee_id, min(depth, dist + 1), conf))

        # Also check for tested_by edges on methods
        for mid in method_ids:
            for edge in store.get_outgoing_edges(mid):
                if edge.type == EdgeType.tested_by:
                    callees.append((edge.target, 1, edge.confidence))
            for edge in store.get_incoming_edges(mid):
                if edge.type == EdgeType.tested_by:
                    callers.append((edge.source, 1, edge.confidence))

    # Count low-confidence edges
    low_conf_count = 0
    for edge in store.get_outgoing_edges(node_id):
        if is_low_confidence(edge.confidence):
            low_conf_count += 1
    for edge in store.get_incoming_edges(node_id):
        if is_low_confidence(edge.confidence):
            low_conf_count += 1

    confirmed_symbols: list[dict] = []
    confirmed_files: dict[str, dict] = {}
    possible_symbols: list[dict] = []
    possible_files: dict[str, dict] = {}
    upstream: list[dict] = []
    downstream: list[dict] = []

    def _symbol_entry(
        symbol_id: str, reason: str, impact_type: str,
        distance: int, confidence: float, node=None,
    ) -> dict:
        n = node or store.get_node(symbol_id)
        return {
            "symbol_id": symbol_id,
            "name": n.name if n else symbol_id,
            "type": n.type.value if (n and hasattr(n.type, "value")) else ("unknown"),
            "file_path": n.file_path if n else "",
            "reason": reason,
            "impact_type": impact_type,
            "distance": distance,
            "confidence": round(confidence, 4),
            "confidence_level": get_confidence_level(confidence),
        }

    def _add_file(files_dict: dict, file_path: str, reason: str, priority: str = "medium") -> None:
        if file_path not in files_dict:
            files_dict[file_path] = {
                "file_path": file_path,
                "reason": reason,
                "priority": priority,
            }
        elif priority == "high" and files_dict[file_path]["priority"] != "high":
            files_dict[file_path]["priority"] = "high"
            files_dict[file_path]["reason"] = reason

    # Direct definition (always confirmed)
    confirmed_symbols.append(_symbol_entry(
        symbol_id=node_id,
        reason="Direct definition — the symbol being modified.",
        impact_type="direct_definition",
        distance=0,
        confidence=1.0,
        node=center,
    ))
    if center.file_path:
        _add_file(confirmed_files, center.file_path,
                  "Direct definition in this file.", "high")

    # Upstream callers
    for caller_id, dist, conf in callers:
        caller_node = store.get_node(caller_id)
        entry = _symbol_entry(
            symbol_id=caller_id,
            reason=f"Calls the target symbol (distance {dist}).",
            impact_type="upstream_caller",
            distance=dist,
            confidence=conf,
            node=caller_node,
        )
        upstream.append(entry)
        if conf >= min_confidence:
            confirmed_symbols.append(entry)
            if caller_node and caller_node.file_path:
                _add_file(confirmed_files, caller_node.file_path,
                          f"Upstream caller at distance {dist}.",
                          "high" if dist <= 1 else "medium")
        else:
            possible_symbols.append(entry)
            if caller_node and caller_node.file_path:
                _add_file(possible_files, caller_node.file_path,
                          f"Possible upstream caller (low confidence: {conf}).", "low")

    # Downstream callees
    for callee_id, dist, conf in callees:
        callee_node = store.get_node(callee_id)
        entry = _symbol_entry(
            symbol_id=callee_id,
            reason=f"Called by the target symbol (distance {dist}).",
            impact_type="downstream_call",
            distance=dist,
            confidence=conf,
            node=callee_node,
        )
        downstream.append(entry)
        if conf >= min_confidence:
            confirmed_symbols.append(entry)
            if callee_node and callee_node.file_path:
                _add_file(confirmed_files, callee_node.file_path,
                          f"Downstream callee at distance {dist}.", "medium")
        else:
            possible_symbols.append(entry)
            if callee_node and callee_node.file_path:
                _add_file(possible_files, callee_node.file_path,
                          f"Possible downstream callee (low confidence: {conf}).", "low")

    # ── Model / config / store dependencies via imports ─────────────────
    def _add_model_config_store_impact() -> None:
        """Find model/config/store classes imported by the center node's file
        AND by files of direct callees (transitively)."""
        if not center.file_path:
            return

        # Collect all files to check: center file + direct callee files
        files_to_check: set[str] = {center.file_path}
        for callee_id, _, _ in callees:
            callee_node = store.get_node(callee_id)
            if callee_node and callee_node.file_path:
                files_to_check.add(callee_node.file_path)

        _seen_imports: set[str] = set()
        qual_to_class: dict[str, GraphNode] = {}
        for n in store.all_nodes():
            if n.type == NodeType.class_ and n.qualified_name:
                qual_to_class[n.qualified_name] = n

        for file_id in files_to_check:
            _process_file_imports(file_id, _seen_imports, qual_to_class)

    def _process_file_imports(
        file_id: str,
        _seen_imports: set[str],
        _qual_to_class: dict[str, Any],
    ) -> None:
        for edge in store.get_outgoing_edges(file_id):
            if edge.type != EdgeType.imports:
                continue
            import_node = store.get_node(edge.target)
            if not import_node or not import_node.qualified_name:
                continue
            class_node = _qual_to_class.get(import_node.qualified_name)
            if not class_node or class_node.id in _seen_imports:
                continue

            tags = class_node.tags
            class_name = class_node.name

            if "model" in tags and "config" not in tags:
                _seen_imports.add(class_node.id)
                confirmed_symbols.append(_symbol_entry(
                    class_node.id,
                    f"Data model `{class_name}` — modifying `{center.name}` may require field additions or schema changes.",
                    "shared_model", distance=1, confidence=0.85,
                    node=class_node,
                ))
                if class_node.file_path:
                    _add_file(confirmed_files, class_node.file_path,
                              "Data model file — changes may require field updates.", "high")
            elif "config" in tags or "settings" in tags:
                _seen_imports.add(class_node.id)
                confirmed_symbols.append(_symbol_entry(
                    class_node.id,
                    f"Configuration `{class_name}` — changes to `{center.name}` may need new config fields.",
                    "config_dependency", distance=1, confidence=0.90,
                    node=class_node,
                ))
                if class_node.file_path:
                    _add_file(confirmed_files, class_node.file_path,
                              "Configuration file — feature changes may need config updates.", "high")
            elif "store" in tags or "persistence" in tags:
                _seen_imports.add(class_node.id)
                confirmed_symbols.append(_symbol_entry(
                    class_node.id,
                    f"Persistence `{class_name}` — behavior changes in `{center.name}` may require store updates.",
                    "upstream_caller", distance=1, confidence=0.85,
                    node=class_node,
                ))
                if class_node.file_path:
                    _add_file(confirmed_files, class_node.file_path,
                              "Persistence layer file — data read/write changes may be needed.", "high")

    _add_model_config_store_impact()

    # ── External / unresolved ─────────────────────────────────────────────
    external_or_unresolved: list[dict] = []
    _seen_external: set[str] = set()

    def _add_external(edge: GraphEdge, target_id: str, role: str) -> None:
        """Add an entry to external_or_unresolved, deduplicating by symbol_id."""
        if target_id in _seen_external:
            return
        _seen_external.add(target_id)
        edge_res = edge.metadata.resolution if edge.metadata else None
        res_str = edge_res.value if edge_res else "unknown"
        ext_type = classify_edge_resolution(edge_res) if edge_res else "unresolved"
        external_or_unresolved.append({
            "symbol_id": target_id,
            "name": target_id,
            "type": "external_symbol",
            "resolution": res_str,
            "category": ext_type,
            "reason": f"{'External or unresolved call target' if role == 'target' else 'External or unresolved caller'} (resolution: {res_str}).",
            "confidence": edge.confidence,
            "confidence_level": get_confidence_level(edge.confidence),
        })

    for edge in store.get_outgoing_edges(node_id):
        if edge.type != EdgeType.calls:
            continue
        target_node = store.get_node(edge.target)
        edge_res = edge.metadata.resolution if edge.metadata else None
        if target_node is None or target_node.type == NodeType.external_symbol or (edge_res is not None and is_unresolved_resolution(edge_res)):
            _add_external(edge, edge.target, "target")
    for edge in store.get_incoming_edges(node_id):
        if edge.type != EdgeType.calls:
            continue
        source_node = store.get_node(edge.source)
        edge_res = edge.metadata.resolution if edge.metadata else None
        if source_node is None or source_node.type == NodeType.external_symbol or (edge_res is not None and is_unresolved_resolution(edge_res)):
            _add_external(edge, edge.source, "source")

    # ── Tests ──────────────────────────────────────────────────────────────
    related_tests: list[dict] = []
    seen_test_ids: set[str] = set()
    has_tests = False

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
                    "reason": "This test directly covers the target symbol.",
                    "confidence": edge.confidence,
                    "confidence_level": get_confidence_level(edge.confidence),
                    "type": "existing",
                })

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
                    "reason": "Test calls the target symbol directly.",
                    "confidence": edge.confidence,
                    "confidence_level": get_confidence_level(edge.confidence),
                    "type": "existing",
                })

    for caller_id, _, _ in callers:
        caller_node = store.get_node(caller_id)
        if caller_node and caller_node.type == NodeType.test and caller_id not in seen_test_ids:
            has_tests = True
            seen_test_ids.add(caller_id)
            related_tests.append({
                "symbol_id": caller_id,
                "name": caller_node.name,
                "file_path": caller_node.file_path or "",
                "reason": "Test is an upstream caller of the target symbol.",
                "confidence": 0.6,
                "confidence_level": get_confidence_level(0.6),
                "type": "existing",
            })
            break

    # ── Risk assessment ────────────────────────────────────────────────────
    level, reasons = _assess_risk(
        store, node_id, center, callers, callees, has_tests, low_conf_count,
    )

    return {
        "risk": {"level": level, "reasons": reasons},
        "confirmed_impact": {
            "symbols": confirmed_symbols,
            "files": list(confirmed_files.values()),
        },
        "possible_impact": {
            "symbols": possible_symbols,
            "files": list(possible_files.values()),
        },
        "upstream_callers": upstream,
        "downstream_callees": downstream,
        "related_tests": related_tests,
        "external_or_unresolved": external_or_unresolved,
    }
