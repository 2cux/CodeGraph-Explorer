"""Call relationship extraction from AST."""

import ast
from pathlib import Path

from codegraph.graph.models import GraphEdge


def extract_calls(tree: ast.Module, source_path: Path) -> list[GraphEdge]:
    """Extract function/method call edges from a parsed AST."""
    ...


def resolve_call_name(node: ast.Call) -> str:
    """Resolve a Call AST node into a qualified name string."""
    ...
