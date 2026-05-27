"""Python AST parser for extracting code structure."""

import ast
from pathlib import Path


def parse_file(path: Path) -> ast.Module:
    """Parse a Python file into an AST."""
    source = path.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(path))


def extract_classes(tree: ast.Module) -> list[ast.ClassDef]:
    """Extract all top-level class definitions from the AST."""
    return [node for node in tree.body if isinstance(node, ast.ClassDef)]


def extract_functions(tree: ast.Module) -> list[ast.FunctionDef]:
    """Extract all top-level function definitions from the AST."""
    return [node for node in tree.body if isinstance(node, ast.FunctionDef)]


def extract_imports(tree: ast.Module) -> list[ast.AST]:
    """Extract all import statements (import / from ... import)."""
    return [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]


def is_test_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if a function definition looks like a test."""
    return node.name.startswith("test_") or node.name == "test"
