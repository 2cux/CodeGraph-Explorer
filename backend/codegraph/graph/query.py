"""Graph query operations — callers, callees, and symbol search."""

from codegraph.graph.store import GraphStore


def get_callers(store: GraphStore, node_id: str) -> list[tuple[str, str]]:
    """Return all callers of a symbol (node_id -> caller info with edge type)."""
    ...


def get_callees(store: GraphStore, node_id: str) -> list[tuple[str, str]]:
    """Return all callees called by the given symbol."""
    ...


def search_symbols(store: GraphStore, query: str) -> list[dict]:
    """Search for symbols by name or file path."""
    ...
