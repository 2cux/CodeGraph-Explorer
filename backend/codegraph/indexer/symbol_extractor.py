"""Symbol extraction from parsed AST nodes."""

import ast
import re
from pathlib import Path

from codegraph.graph.models import GraphNode, NodeType, Location


def build_node_id(rel_path: str, symbol_name: str = "") -> str:
    """Build a stable human-readable node ID.

    File node:          ``src/app/api/auth.py``
    Module node:        ``module:app.api.auth``
    Function node:      ``src/app/api/auth.py::login``
    Method node:        ``src/app/api/auth.py::AuthService.validate_token``
    External symbol:    ``external:fastapi.APIRouter``
    """
    if symbol_name.startswith("external:"):
        return symbol_name
    if symbol_name.startswith("module:"):
        return symbol_name
    if not symbol_name:
        return rel_path
    return f"{rel_path}::{symbol_name}"


def _module_name(rel_path: str) -> str:
    """Convert a relative .py path to a Python module name."""
    stem = rel_path.replace("\\", "/").removesuffix(".py").removesuffix("/__init__")
    return stem.replace("/", ".")


def _extract_docstring(body: list[ast.stmt]) -> str | None:
    """Extract docstring from a list of AST statements."""
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        val = body[0].value.value
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _build_function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Reconstruct a function/method signature from its AST node."""
    args = node.args
    parts: list[str] = []

    # Positional / positional-only args
    arg_offset = 0
    if args.posonlyargs:
        arg_offset = len(args.posonlyargs)
        for a in args.posonlyargs:
            parts.append(_arg_str(a))
        parts.append("/")

    for a in args.args:
        parts.append(_arg_str(a))

    if args.vararg:
        parts.append(f"*{args.vararg.arg}{_annotation_str(args.vararg.annotation)}")

    # Keyword-only args
    if args.kwonlyargs and not args.vararg:
        parts.append("*")
    for a in args.kwonlyargs:
        parts.append(_arg_str(a))

    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}{_annotation_str(args.kwarg.annotation)}")

    sig = f"{node.name}({', '.join(parts)})"
    ret = _annotation_str(node.returns)
    if ret:
        sig += f" -> {ret}"
    return sig


def _arg_str(a: ast.arg) -> str:
    s = a.arg
    ann = _annotation_str(a.annotation)
    if ann:
        s += f": {ann}"
    return s


def _annotation_str(annotation: ast.expr | None) -> str:
    if annotation is None:
        return ""
    # Handle simple names like `str`, `int`
    if isinstance(annotation, ast.Name):
        return annotation.id
    # Handle subscript types like `list[str]`, `dict[str, Any]`
    if isinstance(annotation, ast.Subscript):
        return f"{_annotation_str(annotation.value)}[{_annotation_str(annotation.slice)}]"
    # Handle attribute types like `pathlib.Path`
    if isinstance(annotation, ast.Attribute):
        return f"{_annotation_str(annotation.value)}.{annotation.attr}"
    # Handle tuples like `tuple[int, str]`
    if isinstance(annotation, ast.Tuple):
        inner = ", ".join(_annotation_str(e) for e in annotation.elts)
        return f"[{inner}]"
    # Handle constant strings (forward references)
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value
    # Fallback
    return ast.unparse(annotation)


def _visibility(name: str) -> str:
    if name.startswith("__"):
        return "private"
    if name.startswith("_"):
        return "protected"
    return "public"


def _code_preview(node: ast.AST) -> str:
    """Return the first few lines of source code for a node."""
    try:
        lines = ast.unparse(node).splitlines()
    except Exception:
        return ""
    # Return at most 6 lines
    preview = "\n".join(lines[:6])
    if len(lines) > 6:
        preview += "\n    ..."
    return preview


def _make_location(node: ast.AST) -> Location:
    return Location(
        line_start=node.lineno,
        line_end=getattr(node, "end_lineno", node.lineno),
        column_start=getattr(node, "col_offset", None),
        column_end=getattr(node, "end_col_offset", None),
    )


def extract_symbols(rel_path: str, tree: ast.Module) -> list[GraphNode]:
    """Extract GraphNode objects from a parsed AST.

    *rel_path* is the path relative to the project root, e.g. ``app/api/auth.py``.
    """
    nodes: list[GraphNode] = []
    module = _module_name(rel_path)

    # ── file node ──────────────────────────────────────────────────────
    nodes.append(GraphNode(
        id=rel_path,
        type=NodeType.file,
        name=Path(rel_path).name,
        file_path=rel_path,
        module=module,
        display_name=rel_path,
    ))

    # ── module node ────────────────────────────────────────────────────
    module_id = f"module:{module}"
    nodes.append(GraphNode(
        id=module_id,
        type=NodeType.module,
        name=module.rsplit(".", 1)[-1] if "." in module else module,
        qualified_name=module,
        file_path=rel_path,
        module=module,
        display_name=module,
    ))

    # ── imports ────────────────────────────────────────────────────────
    for imp in tree.body:
        if isinstance(imp, ast.Import):
            for alias in imp.names:
                alias_name = alias.asname or alias.name
                is_external = "." not in alias.name and alias.name.split(".")[0] not in (
                    "app", "src", "backend")
                node_type = NodeType.external_symbol if is_external else NodeType.import_
                nid = f"external:{alias.name}" if is_external else f"{rel_path}::import.{alias_name}"
                nodes.append(GraphNode(
                    id=nid,
                    type=node_type,
                    name=alias.asname or alias.name,
                    qualified_name=alias.name,
                    file_path=rel_path,
                    module=module,
                    display_name=alias.asname or alias.name,
                    location=_make_location(imp),
                    visibility="public",
                ))
        elif isinstance(imp, ast.ImportFrom):
            base = imp.module or ""
            for alias in imp.names:
                alias_name = alias.asname or alias.name
                full_name = f"{base}.{alias.name}" if base else alias.name
                is_external = bool(base) and base.split(".")[0] not in (
                    "app", "src", "backend")
                node_type = NodeType.external_symbol if is_external else NodeType.import_
                nid = f"external:{full_name}" if is_external else f"{rel_path}::import.{alias_name}"
                nodes.append(GraphNode(
                    id=nid,
                    type=node_type,
                    name=alias.asname or alias.name,
                    qualified_name=full_name,
                    file_path=rel_path,
                    module=module,
                    display_name=alias.asname or alias.name,
                    location=_make_location(imp),
                    visibility="public",
                ))

    # ── functions (top-level) ──────────────────────────────────────────
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef):
            _extract_function(nodes, fn, rel_path, module, parent_class=None)
        elif isinstance(fn, ast.AsyncFunctionDef):
            _extract_function(nodes, fn, rel_path, module, parent_class=None)

    # ── classes ────────────────────────────────────────────────────────
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef):
            _extract_class(nodes, cls, rel_path, module)

    return nodes


def _extract_function(
    nodes: list[GraphNode],
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    rel_path: str,
    module: str,
    parent_class: str | None,
) -> None:
    """Extract a function/method node and add it to the list."""
    is_test = fn.name.startswith("test_") or fn.name == "test"

    if parent_class:
        symbol_name = f"{parent_class}.{fn.name}"
        node_type = NodeType.method
        qualified_name = f"{module}.{parent_class}.{fn.name}"
        display_name = f"{parent_class}.{fn.name}"
    else:
        symbol_name = fn.name
        node_type = NodeType.test if is_test else NodeType.function
        qualified_name = f"{module}.{fn.name}"
        display_name = fn.name

    tags = ["async"] if isinstance(fn, ast.AsyncFunctionDef) else []
    if is_test:
        tags.append("test")

    nodes.append(GraphNode(
        id=build_node_id(rel_path, symbol_name),
        type=node_type,
        name=fn.name,
        qualified_name=qualified_name,
        display_name=display_name,
        file_path=rel_path,
        module=module,
        location=_make_location(fn),
        signature=_build_function_signature(fn),
        docstring=_extract_docstring(fn.body),
        code_preview=_code_preview(fn),
        visibility=_visibility(fn.name),
        tags=tags,
    ))


def _extract_class(
    nodes: list[GraphNode],
    cls: ast.ClassDef,
    rel_path: str,
    module: str,
) -> None:
    """Extract a class node and its methods."""
    qualified_name = f"{module}.{cls.name}"
    tags = []
    # Check for dataclass decorator
    for dec in cls.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "dataclass":
            tags.append("dataclass")
            break
        if isinstance(dec, ast.Attribute) and dec.attr == "dataclass":
            tags.append("dataclass")
            break

    nodes.append(GraphNode(
        id=build_node_id(rel_path, cls.name),
        type=NodeType.class_,
        name=cls.name,
        qualified_name=qualified_name,
        display_name=cls.name,
        file_path=rel_path,
        module=module,
        location=_make_location(cls),
        docstring=_extract_docstring(cls.body),
        code_preview=_code_preview(cls),
        visibility=_visibility(cls.name),
        tags=tags,
    ))

    # Methods
    for item in cls.body:
        if isinstance(item, ast.FunctionDef):
            _extract_function(nodes, item, rel_path, module, parent_class=cls.name)
        elif isinstance(item, ast.AsyncFunctionDef):
            _extract_function(nodes, item, rel_path, module, parent_class=cls.name)
