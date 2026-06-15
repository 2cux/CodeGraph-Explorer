"""Shared helpers for builtin harness modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from codegraph.graph.models import CodeGraph, GraphEdge, GraphNode
from codegraph.graph.store import GraphStore
from codegraph.storage.sqlite_store import SqliteStore


def coerce_str_list(value: Any) -> list[str]:
    """Normalize a string or list-like input into a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    raise TypeError(f"Expected list-like or comma-separated string, got {type(value).__name__}")


def coerce_bool(value: Any, *, default: bool) -> bool:
    """Normalize bool-like input values using Pydantic coercion."""
    if value is None:
        return default
    return TypeAdapter(bool).validate_python(value)


def find_codegraph_dir(project_root: Path) -> Path:
    """Find the active ``.codegraph`` directory from a project root candidate."""
    resolved_root = project_root.resolve()
    for parent in [resolved_root] + list(resolved_root.parents):
        candidate = parent / ".codegraph"
        if (candidate / "index.sqlite").exists() or (candidate / "graph.json").exists():
            return candidate
    raise FileNotFoundError(
        f"No .codegraph directory found from {resolved_root}. Run 'codegraph init' first."
    )


def load_graph_store(project_root: Path) -> tuple[GraphStore, Path]:
    """Load a graph store for harness workflow modules."""
    cg_dir = find_codegraph_dir(project_root)
    sqlite_path = cg_dir / "index.sqlite"
    store = GraphStore()

    if sqlite_path.exists():
        sql_store = SqliteStore(sqlite_path)
        try:
            sql_store.initialize()
            node_adapter = TypeAdapter(list[GraphNode])
            edge_adapter = TypeAdapter(list[GraphEdge])
            store.load_from_lists(
                node_adapter.validate_python(sql_store.load_all_nodes()),
                edge_adapter.validate_python(sql_store.load_all_edges()),
            )
            return store, cg_dir
        finally:
            sql_store.close()

    graph_path = cg_dir / "graph.json"
    if not graph_path.exists():
        raise FileNotFoundError(f"Missing graph store files in {cg_dir}")
    graph = CodeGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    store.load_from_graph(graph)
    return store, cg_dir


def json_report(title: str, result: dict[str, Any]) -> str:
    """Render a compact Markdown report for harness artifacts."""
    body = json.dumps(result, ensure_ascii=False, indent=2)
    return f"# {title}\n\n```json\n{body}\n```\n"
