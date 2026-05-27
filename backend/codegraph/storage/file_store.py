"""JSON file-based storage for graph data."""

from pathlib import Path


class FileStore:
    """Read/write graph nodes and edges to JSON files."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def save_nodes(self, nodes: list[dict]) -> None:
        ...

    def load_nodes(self) -> list[dict]:
        ...

    def save_edges(self, edges: list[dict]) -> None:
        ...

    def load_edges(self) -> list[dict]:
        ...
