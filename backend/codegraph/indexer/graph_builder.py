"""Graph builder that orchestrates indexing and constructs the code graph."""

from pathlib import Path

from codegraph.graph.models import GraphNode, GraphEdge


def build_index(root: Path) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Scan, parse, extract symbols and calls, and return the complete graph."""
    ...


def build_index_from_paths(paths: list[Path]) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Build index from a pre-discovered list of file paths."""
    ...
