"""JSON file-based storage for graph data."""

import json
import os
from pathlib import Path

from codegraph.graph.models import IndexMetadata


class FileStore:
    """Read/write graph nodes and edges to JSON files."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_nodes(self, nodes: list[dict]) -> None:
        path = self.base_dir / "nodes.json"
        self._atomic_write_text(path, json.dumps(nodes, indent=2, ensure_ascii=False))

    def load_nodes(self) -> list[dict]:
        path = self.base_dir / "nodes.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def save_edges(self, edges: list[dict]) -> None:
        path = self.base_dir / "edges.json"
        self._atomic_write_text(path, json.dumps(edges, indent=2, ensure_ascii=False))

    def load_edges(self) -> list[dict]:
        path = self.base_dir / "edges.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def save_metadata(self, metadata: IndexMetadata) -> None:
        path = self.base_dir / "metadata.json"
        self._atomic_write_text(path, metadata.model_dump_json(indent=2, exclude_none=True))

    def load_metadata(self) -> IndexMetadata | None:
        path = self.base_dir / "metadata.json"
        if not path.exists():
            return None
        return IndexMetadata.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        """Atomically write UTF-8 text without corrupting the previous file."""
        tmp = path.with_name(f".{path.name}.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
