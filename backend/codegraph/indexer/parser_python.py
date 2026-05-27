"""Python AST parser for extracting code structure."""

import ast
from pathlib import Path


def parse_file(path: Path) -> ast.Module:
    """Parse a Python file into an AST."""
    ...


def extract_classes(tree: ast.Module) -> list[ast.ClassDef]:
    """Extract all top-level class definitions from the AST."""
    ...


def extract_functions(tree: ast.Module) -> list[ast.FunctionDef]:
    """Extract all top-level function definitions from the AST."""
    ...
