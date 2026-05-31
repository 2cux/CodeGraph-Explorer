"""Graph query operations — callers, callees, symbol search, subgraph, and stats."""

from codegraph.graph.store import GraphStore
from codegraph.graph.models import GraphNode, GraphEdge, EdgeType


# ── Callers / Callees ──────────────────────────────────────────────────


def get_callers(store: GraphStore, node_id: str) -> list[tuple[str, str]]:
    """Return all callers of a symbol ``(caller_id, edge_type)``."""
    callers: list[tuple[str, str]] = []
    for edge in store.get_incoming_edges(node_id):
        if edge.type == EdgeType.calls:
            callers.append((edge.source, edge.type.value))
    return callers


def get_callees(store: GraphStore, node_id: str) -> list[tuple[str, str]]:
    """Return all callees called by the given symbol ``(callee_id, edge_type)``."""
    callees: list[tuple[str, str]] = []
    for edge in store.get_outgoing_edges(node_id):
        if edge.type == EdgeType.calls:
            callees.append((edge.target, edge.type.value))
    return callees


# ── Search ─────────────────────────────────────────────────────────────


def search_symbols(
    store: GraphStore,
    query: str = "",
    type_filter: str | None = None,
    file_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Search for symbols by name, file path, or docstring.

    Returns ``{"results": [...], "total": int}`` where each result has keys:
      ``id``, ``symbol_id``, ``name``, ``type``, ``file_path``,
      ``score``, ``match_sources``.
    """
    nodes = store.search_nodes(query)
    q = query.lower() if query else ""
    results: list[dict] = []

    for node in nodes:
        # Apply type filter
        if type_filter and node.type.value != type_filter:
            continue
        # Apply file filter
        if file_filter and file_filter not in node.file_path:
            continue

        score = 0.0
        sources: list[str] = []

        if q and q in node.id.lower():
            score = max(score, 1.0)
            sources.append("node_id")

        if q and node.name:
            if q == node.name.lower():
                score = max(score, 1.0)
                sources.append("exact_name")
            elif q in node.name.lower():
                score = max(score, 0.8)
                if "exact_name" not in sources:
                    sources.append("name_fragment")

        if q and node.file_path and q in node.file_path.lower():
            score = max(score, 0.7)
            sources.append("file_path")

        if q and node.qualified_name and q in node.qualified_name.lower():
            score = max(score, 0.9)
            sources.append("qualified_name")

        if q and node.docstring and q in node.docstring.lower():
            score = max(score, 0.5)
            sources.append("docstring")

        # Even with empty query every node gets a default score
        if not q:
            score = 0.5

        results.append({
            "id": node.id,
            "symbol_id": node.id,
            "name": node.name,
            "type": node.type.value,
            "file_path": node.file_path,
            "score": score,
            "match_sources": sources,
            "tags": node.tags,
            "line_start": node.location.line_start if node.location else None,
            "line_end": node.location.line_end if node.location else None,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    total = len(results)
    paginated = results[offset:offset + limit]

    return {"results": paginated, "total": total}


# ── Subgraph ───────────────────────────────────────────────────────────


def get_subgraph(
    store: GraphStore,
    center_node_id: str,
    depth: int = 1,
    max_nodes: int = 100,
) -> dict:
    """Extract a local subgraph centered on *center_node_id* up to *depth*.

    Returns ``{"center_node_id", "depth", "nodes", "edges"}``.
    """
    visited_nodes: set[str] = set()
    visited_edges: set[tuple[str, str, str]] = set()
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    def walk(current_id: str, current_depth: int) -> None:
        if current_depth > depth or current_id in visited_nodes:
            return
        if len(nodes) >= max_nodes:
            return
        visited_nodes.add(current_id)

        current_node = store.get_node(current_id)
        if current_node:
            nodes.append(current_node)

        neighbors = store.get_neighbors(current_id)
        for neighbor, edge in neighbors:
            if len(nodes) >= max_nodes:
                break
            edge_key = (edge.source, edge.target, edge.type.value if hasattr(edge.type, 'value') else str(edge.type))
            if edge_key not in visited_edges:
                visited_edges.add(edge_key)
                edges.append(edge)
            walk(neighbor.id, current_depth + 1)

    walk(center_node_id, 0)

    return {
        "center_node_id": center_node_id,
        "depth": depth,
        "nodes": nodes,
        "edges": edges,
    }


# ── Stats ──────────────────────────────────────────────────────────────


def get_graph_stats(store: GraphStore) -> dict:
    """Compute aggregate statistics for the current graph.

    Returns a dict with keys:
      ``symbol_count``, ``file_count``, ``edge_count``,
      ``function_count``, ``method_count``, ``class_count``,
      ``module_count``, ``test_count``, ``import_count``,
      ``low_confidence_edges``, ``low_confidence_ratio``.
    """
    nodes = store.all_nodes()
    edges = store.all_edges()

    type_counts: dict[str, int] = {}
    for n in nodes:
        type_counts[n.type.value] = type_counts.get(n.type.value, 0) + 1

    files = {n.file_path for n in nodes if n.file_path}
    low_conf_edges = [e for e in edges if e.confidence < 0.6]
    low_conf_ratio = len(low_conf_edges) / len(edges) if edges else 0.0

    return {
        "symbol_count": len(nodes),
        "file_count": len(files),
        "edge_count": len(edges),
        "function_count": type_counts.get("function", 0),
        "method_count": type_counts.get("method", 0),
        "class_count": type_counts.get("class", 0),
        "module_count": type_counts.get("module", 0),
        "test_count": type_counts.get("test", 0),
        "import_count": type_counts.get("import", 0),
        "low_confidence_edges": len(low_conf_edges),
        "low_confidence_ratio": round(low_conf_ratio, 4),
    }
