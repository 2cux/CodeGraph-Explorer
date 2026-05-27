"""Context Pack builder — generates task-aware code context packages."""

from codegraph.context.models import ContextPack
from codegraph.graph.store import GraphStore


def build_context_pack(
    store: GraphStore,
    task_description: str,
    max_tokens: int = 32000,
) -> ContextPack:
    """Build a Context Pack from the graph store for the given task."""
    ...
