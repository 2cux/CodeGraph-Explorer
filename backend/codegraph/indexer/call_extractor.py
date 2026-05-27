"""Call relationship extraction from AST."""

import ast
from pathlib import Path

from codegraph.graph.models import (
    GraphEdge,
    EdgeType,
    EdgeLocation,
    EdgeMetadata,
    Resolution,
)

# ── Confidence lookup table (PRD §12.8) ─────────────────────────────
_CONFIDENCE: dict[Resolution, float] = {
    Resolution.exact_ast_match: 1.0,
    Resolution.same_file_exact: 0.95,
    Resolution.import_resolved: 0.9,
    Resolution.class_method_resolved: 0.8,
    Resolution.type_hint_resolved: 0.75,
    Resolution.test_name_heuristic: 0.65,
    Resolution.attribute_guess: 0.55,
    Resolution.external_symbol: 0.4,
    Resolution.unresolved: 0.2,
}


def resolve_call_name(node: ast.Call) -> str:
    """Resolve a Call AST node into a qualified name string.

    Returns the callable name as written in source, e.g. ``login``,
    ``self.save_token``, ``revoke_token``.
    """
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = []
        current = func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        else:
            parts.append(ast.unparse(current))
        return ".".join(reversed(parts))
    return ast.unparse(func)


class _FileContext:
    """Minimal symbol context for a single file."""

    def __init__(self, tree: ast.Module, source_path: Path) -> None:
        self.rel_path = _rel_str(source_path)
        self.functions: set[str] = set()
        self.methods: dict[str, set[str]] = {}  # class_name -> method names
        self.current_class: str | None = None
        self.imported_names: dict[str, tuple[str, str]] = {}  # local -> (module, original_name)
        self.imported_modules: dict[str, str] = {}  # alias -> module

        self._build(tree)

    def _build(self, tree: ast.Module) -> None:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                self.functions.add(node.name)
            elif isinstance(node, ast.AsyncFunctionDef):
                self.functions.add(node.name)
            elif isinstance(node, ast.ClassDef):
                self.methods[node.name] = set()
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.methods[node.name].add(item.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name
                    self.imported_names[local] = ("", alias.name)
                    top = alias.name.split(".")[0]
                    self.imported_modules[local] = alias.name
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                for alias in node.names:
                    local = alias.asname or alias.name
                    full = f"{base}.{alias.name}" if base else alias.name
                    self.imported_names[local] = (base, alias.name)


def _rel_str(path: Path) -> str:
    """Convert a Path to a forward-slash relative string."""
    return path.as_posix()


def _edge_id(counter: int) -> str:
    return f"edge_{counter:04d}"


def extract_calls(tree: ast.Module, source_path: Path, rel_path: str | None = None,
                  edge_counter: list[int] | None = None) -> list[GraphEdge]:
    """Extract function/method call edges from a parsed AST.

    Walks the AST and produces ``calls`` edges with appropriate
    confidence levels, plus ``inherits`` edges.

    *source_path* — used to derive the relative path for node IDs.
    *edge_counter* — mutable shared counter for global unique edge IDs
                     (pass ``[0]`` from caller).
    """
    rel = rel_path or _rel_str(source_path)
    ctx = _FileContext(tree, source_path)

    collector = _CallCollector(ctx, rel, edge_counter or [0])
    collector.visit(tree)
    return collector.edges


# ── Internal visitor ──────────────────────────────────────────────────

class _CallCollector(ast.NodeVisitor):
    """AST visitor that collects call/inherit edges."""

    def __init__(self, ctx: _FileContext, rel_path: str,
                 edge_counter: list[int]) -> None:
        self.ctx = ctx
        self.rel = rel_path
        self.edges: list[GraphEdge] = []
        self._counter = edge_counter
        self._class_stack: list[str] = []
        self._func_stack: list[str] = []  # track enclosing function

    def _next_edge_id(self) -> str:
        self._counter[0] += 1
        return _edge_id(self._counter[0])

    # ── class tracking ─────────────────────────────────────────────

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self._process_inherits(node)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    # ── inheritance ────────────────────────────────────────────────

    def _process_inherits(self, node: ast.ClassDef) -> None:
        for base in node.bases:
            if isinstance(base, ast.Name):
                target_id = self._resolve_inherit_target(base.id)
                if target_id:
                    self.edges.append(GraphEdge(
                        id=self._next_edge_id(),
                        type=EdgeType.inherits,
                        source=f"{self.rel}::{node.name}",
                        target=target_id,
                        confidence=0.95,
                        source_location=EdgeLocation(
                            file_path=self.rel,
                            line_start=node.lineno,
                            line_end=getattr(node, "end_lineno", node.lineno),
                        ),
                        metadata=EdgeMetadata(
                            call_expr=base.id,
                            resolution=Resolution.same_file_exact,
                        ),
                    ))

    def _resolve_inherit_target(self, name: str) -> str:
        if name in self.ctx.functions or name in self.ctx.methods.get("", set()):
            return f"{self.rel}::{name}"
        if name in self.ctx.imported_names:
            mod, orig = self.ctx.imported_names[name]
            return f"external:{mod}.{orig}" if mod else f"external:{orig}"
        return f"external:{name}"

    # ── calls ──────────────────────────────────────────────────────

    def visit_Call(self, node: ast.Call) -> None:
        call_expr = resolve_call_name(node)
        source_id = self._current_function_id(node)

        target_id, resolution = self._resolve_call(node)

        if target_id:
            self.edges.append(GraphEdge(
                id=self._next_edge_id(),
                type=EdgeType.calls,
                source=source_id or self.rel,
                target=target_id,
                confidence=_CONFIDENCE.get(resolution, 0.2),
                source_location=EdgeLocation(
                    file_path=self.rel,
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                ),
                metadata=EdgeMetadata(
                    call_expr=call_expr,
                    resolution=resolution,
                ),
            ))

        # Continue traversal for nested calls (e.g., f(g())
        self.generic_visit(node)

    def _current_function_id(self, call_node: ast.Call) -> str | None:
        """Find the enclosing function and build its node ID if applicable."""
        if not self._func_stack:
            return None
        func_name = self._func_stack[-1]
        current_class = self._class_stack[-1] if self._class_stack else None
        if current_class:
            return f"{self.rel}::{current_class}.{func_name}"
        return f"{self.rel}::{func_name}"

    def _resolve_call(self, node: ast.Call) -> tuple[str, Resolution]:
        """Try to resolve a Call node to a target node ID and resolution.

        Returns ``(target_id, resolution)``.
        """
        func = node.func

        # ── simple name: login(...) ──────────────────────────────
        if isinstance(func, ast.Name):
            return self._resolve_name_call(func.id)

        # ── attribute call: obj.method(...) ──────────────────────
        if isinstance(func, ast.Attribute):
            return self._resolve_attribute_call(func)

        return "", Resolution.unresolved

    def _resolve_name_call(self, name: str) -> tuple[str, Resolution]:
        """Resolve a plain name call."""
        current_class = self._class_stack[-1] if self._class_stack else None

        # Same-file top-level function
        if name in self.ctx.functions:
            return f"{self.rel}::{name}", Resolution.same_file_exact

        # Current class method (self.xxx() — name-only may match)
        if current_class and name in self.ctx.methods.get(current_class, set()):
            return f"{self.rel}::{current_class}.{name}", Resolution.class_method_resolved

        # Imported name
        if name in self.ctx.imported_names:
            mod, orig = self.ctx.imported_names[name]
            if mod:
                return f"external:{mod}.{orig}", Resolution.import_resolved
            return f"external:{orig}", Resolution.import_resolved

        # Maybe it's a module-level call to an unknown symbol
        return f"external:{name}", Resolution.external_symbol

    def _resolve_attribute_call(self, node: ast.Attribute) -> tuple[str, Resolution]:
        """Resolve an attribute-style call like obj.method()."""
        attr = node.attr
        current_class = self._class_stack[-1] if self._class_stack else None

        # self.method() — same-class method call
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            if current_class and attr in self.ctx.methods.get(current_class, set()):
                return f"{self.rel}::{current_class}.{attr}", Resolution.class_method_resolved

        # imported_module.function() — e.g. app.store.token_store.save_token(...)
        if isinstance(node.value, ast.Name):
            obj_name = node.value.id
            if obj_name in self.ctx.imported_modules:
                full_module = self.ctx.imported_modules[obj_name]
                return f"external:{full_module}.{attr}", Resolution.import_resolved
            if obj_name in self.ctx.imported_names:
                mod, orig = self.ctx.imported_names[obj_name]
                return f"external:{mod}.{attr}" if mod else f"external:{orig}.{attr}", Resolution.import_resolved

        # Unresolved attribute call — fall back
        return "", Resolution.unresolved
