"""Symbol extraction from parsed AST nodes."""

import ast
from pathlib import Path

from codegraph.graph.models import GraphNode


def extract_symbols(path: Path, tree: ast.Module) -> list[GraphNode]:
    """Extract GraphNode objects from a parsed AST."""
    ...


def build_node_id(path: Path, symbol_name: str) -> str:
    """Build a stable human-readable node ID like `path/to/module.py::ClassName`."""
    ...
