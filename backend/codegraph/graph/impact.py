"""Impact analysis — determine what is affected by modifying a symbol."""

from codegraph.graph.store import GraphStore


def analyze_impact(
    store: GraphStore, node_id: str, depth: int = 2
) -> dict:
    """Analyze the impact surface of modifying a symbol up to given depth."""
    ...


def transitive_callers(
    store: GraphStore, node_id: str, depth: int
) -> list[str]:
    """Traverse up the call chain to find all transitive callers."""
    ...
