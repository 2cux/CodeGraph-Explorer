"""Entry point ranking and relevance scoring for Context Pack."""

from codegraph.graph.models import GraphNode


def rank_entry_points(
    task_description: str,
    candidates: list[GraphNode],
) -> list[tuple[GraphNode, float]]:
    """Rank candidate entry points by relevance to the task description."""
    ...


def score_relevance(node: GraphNode, task_description: str) -> float:
    """Score a single node's relevance to the task."""
    ...
