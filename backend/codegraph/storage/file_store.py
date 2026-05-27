"""JSON file-based storage for graph data."""

import json
from pathlib import Path


class FileStore:
    """Read/write graph nodes and edges to JSON files."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_nodes(self, nodes: list[dict]) -> None:
        path = self.base_dir / "nodes.json"
        path.write_text(json.dumps(nodes, indent=2, ensure_ascii=False), encoding="utf-8")

    def load_nodes(self) -> list[dict]:
        path = self.base_dir / "nodes.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def save_edges(self, edges: list[dict]) -> None:
        path = self.base_dir / "edges.json"
        path.write_text(json.dumps(edges, indent=2, ensure_ascii=False), encoding="utf-8")

    def load_edges(self) -> list[dict]:
        path = self.base_dir / "edges.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))
