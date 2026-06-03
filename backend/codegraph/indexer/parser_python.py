"""Python AST parser for extracting code structure."""

import ast
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_file(path: Path) -> ast.Module:
    """Parse a Python file into an AST.

    Returns an empty ``ast.Module`` on syntax errors so the indexer can
    continue processing other files.
    """
    source = path.read_text(encoding="utf-8")
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        logger.warning("Syntax error in %s — skipping", path)
        return ast.Module(body=[], type_ignores=[])


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
