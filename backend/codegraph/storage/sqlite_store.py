"""SQLite-based storage for graph data."""

from pathlib import Path


class SqliteStore:
    """Read/write graph data to a local SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def initialize(self) -> None:
        """Create tables if they don't exist."""
        ...

    def save_nodes(self, nodes: list[dict]) -> None:
        ...

    def save_edges(self, edges: list[dict]) -> None:
        ...

    def query_nodes(self, filters: dict | None = None) -> list[dict]:
        ...
