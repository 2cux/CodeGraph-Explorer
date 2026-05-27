"""Graph query operations — callers, callees, and symbol search."""

from codegraph.graph.store import GraphStore
from codegraph.graph.models import EdgeType


def get_callers(store: GraphStore, node_id: str) -> list[tuple[str, str]]:
    """Return all callers of a symbol (node_id -> (caller_id, edge_type))."""
    callers: list[tuple[str, str]] = []
    for edge in store.get_incoming_edges(node_id):
        if edge.type == EdgeType.calls:
            callers.append((edge.source, edge.type.value))
    return callers


def get_callees(store: GraphStore, node_id: str) -> list[tuple[str, str]]:
    """Return all callees called by the given symbol.

    Returns ``(callee_id, edge_type)`` tuples.
    """
    callees: list[tuple[str, str]] = []
    for edge in store.get_outgoing_edges(node_id):
        if edge.type == EdgeType.calls:
            callees.append((edge.target, edge.type.value))
    return callees


def search_symbols(store: GraphStore, query: str) -> list[dict]:
    """Search for symbols by name, file path, or docstring.

    Returns a list of dicts with keys:
      id, name, type, file_path, score, match_sources
    """
    nodes = store.search_nodes(query)
    results: list[dict] = []

    q = query.lower() if query else ""

    for node in nodes:
        score = 0.0
        sources: list[str] = []

        if q and q in node.id.lower():
            score = max(score, 1.0)
            sources.append("node_id")

        if q and node.name and q == node.name.lower():
            score = max(score, 1.0)
            sources.append("exact_name")
        elif q and node.name and q in node.name.lower():
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

        results.append({
            "id": node.id,
            "symbol_id": node.id,
            "name": node.name,
            "type": node.type.value,
            "file_path": node.file_path,
            "score": score,
            "match_sources": sources,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results
