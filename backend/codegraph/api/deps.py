"""API dependencies — shared store instance."""
from codegraph.graph.store import GraphStore

_store: GraphStore | None = None


def init_store(store: GraphStore) -> None:
    global _store
    _store = store


def get_store() -> GraphStore:
    if _store is None:
        raise RuntimeError(
            "GraphStore not initialized. Run 'codegraph index' first."
        )
    return _store
