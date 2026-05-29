"""Call relationship extraction from AST.

Handles 6 cross-file import/call patterns for accurate call resolution:

1. ``from a.b import func`` → ``func()`` → ``a/b.py::func``
2. ``import a.b.c`` → ``a.b.c.func()`` → ``a/b/c.py::func``
3. ``import a.b.c as m`` → ``m.func()`` → ``a/b/c.py::func``
4. ``from a.b import func as f`` → ``f()`` → ``a/b.py::func``
5. ``from .b import func`` (relative, level=1) → ``a/b.py::func``
6. ``from ..b.c import func`` (relative, level=2) → ``b/c.py::func``
"""

import ast
from pathlib import Path

from codegraph.graph.models import (
    GraphEdge,
    EdgeType,
    EdgeLocation,
    EdgeMetadata,
    Resolution,
)
from codegraph.graph.confidence import get_confidence


# ── Helpers ──────────────────────────────────────────────────────────

def _rel_str(path: Path) -> str:
    """Convert a Path to a forward-slash relative string."""
    return path.as_posix()


def _file_module(rel_path: str) -> str:
    """Derive a Python module name from a file's relative path."""
    stem = rel_path.replace("\\", "/").removesuffix(".py").removesuffix("/__init__")
    return stem.replace("/", ".")


def _edge_id(counter: int) -> str:
    return f"edge_{counter:04d}"


def _extract_type_name(annotation: ast.expr) -> str | None:
    """Extract a simple class name from an AST type annotation.

    Returns the bare class name for ``ast.Name`` nodes (e.g. ``AuthService``),
    or ``None`` for complex types (``list[str]``, ``Optional[X]``, etc.)
    that require full type resolution.
    """
    if isinstance(annotation, ast.Name):
        return annotation.id
    return None


def resolve_call_name(node: ast.Call) -> str:
    """Resolve a Call AST node into a qualified name string.

    Returns the callable name as written in source, e.g. ``login``,
    ``self.save_token``, ``revoke_token``.
    """
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return _reconstruct_attribute(func)
    return ast.unparse(func)


def _reconstruct_attribute(node: ast.Attribute) -> str:
    """Reconstruct the full dotted name from a (possibly chained) Attribute node.

    ``a.b.c.func`` → ``"a.b.c.func"``
    """
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    else:
        parts.append(ast.unparse(current))
    return ".".join(reversed(parts))


# ── Import resolver ──────────────────────────────────────────────────

class _ImportResolver:
    """Tracks import statements and resolves local names to fully qualified symbols.

    Maintains three internal maps:

    * **name_to_target**: local name → ``"full.module.OriginalName"``
      For ``from X import Y [as Z]`` patterns. Used when the call is a
      plain ``Name(...)`` node.

    * **alias_to_module**: local alias → ``"full.module.path"``
      For ``import X [as Y]`` patterns. Used when the call is an
      ``Attribute(Name(alias), attr)`` node.

    * **known_modules**: set of all imported module paths.
      Used for chained-attribute calls like ``a.b.c.func()`` where the
      full expression is split into ``(module_prefix, func_name)`` pairs.
    """

    def __init__(self, file_module: str) -> None:
        self.file_module = file_module
        self.name_to_target: dict[str, str] = {}
        self.alias_to_module: dict[str, str] = {}
        self.known_modules: set[str] = set()
        self.name_to_kind: dict[str, Resolution] = {}

    # ── building the map ─────────────────────────────────────────

    def _resolve_relative_module(self, base: str | None, level: int) -> str:
        """Resolve a relative import to an absolute module path.

        *level* 0 means absolute; level N means go up N-1 parent packages.
        """
        if level == 0:
            return base or ""
        parts = self.file_module.split(".")
        if level > len(parts):
            # Beyond top-level — keep as-is (can't resolve further)
            return base or ""
        parent = ".".join(parts[:-level])
        if base:
            return f"{parent}.{base}" if parent else base
        return parent

    def add_import(self, alias: ast.alias) -> None:
        """Process ``import X`` or ``import X as Y``."""
        full_module = alias.name
        # The Python-visible local name is the first component
        local = alias.asname or alias.name.split(".")[0]
        self.alias_to_module[local] = full_module
        self.known_modules.add(full_module)

    def add_import_from(self, alias: ast.alias, module: str | None,
                        level: int) -> None:
        """Process ``from [.]module import name [as alias]``."""
        abs_module = self._resolve_relative_module(module, level)
        local = alias.asname or alias.name
        original = alias.name
        if abs_module:
            full_symbol = f"{abs_module}.{original}"
            self.known_modules.add(abs_module)
        else:
            full_symbol = original
        self.name_to_target[local] = full_symbol
        # Record the import kind for granular resolution
        if level > 0:
            self.name_to_kind[local] = Resolution.relative_import_resolved
        elif alias.asname:
            self.name_to_kind[local] = Resolution.imported_function_alias
        else:
            self.name_to_kind[local] = Resolution.imported_function_exact

    # ── resolving calls ──────────────────────────────────────────

    def resolve_name(self, local_name: str) -> str | None:
        """Resolve a plain name call to a fully qualified symbol.

        Returns ``"full.module.FuncName"`` or None.
        """
        return self.name_to_target.get(local_name)

    def resolve_name_kind(self, local_name: str) -> Resolution:
        """Return the resolution kind for a name import, or imported_function_exact."""
        return self.name_to_kind.get(local_name, Resolution.imported_function_exact)

    def resolve_attribute(self, obj_name: str, attr_name: str) -> str | None:
        """Resolve ``obj.attr()`` via an import alias.

        E.g. ``token_store.save_token()`` where ``import app.store.token_store as token_store``.
        Returns ``"app.store.token_store.save_token"`` or None.
        """
        module = self.alias_to_module.get(obj_name)
        if module:
            return f"{module}.{attr_name}"
        return None

    def resolve_chained(self, full_expr: str) -> str | None:
        """Resolve a chained attribute call like ``a.b.c.func()``.

        Tries all ``(module_prefix, func_path)`` splits and checks whether
        the module prefix is a known imported module.
        """
        parts = full_expr.split(".")
        # Try the longest module-prefix first, e.g. "a.b.c" for "a.b.c.func"
        for i in range(len(parts) - 1, 0, -1):
            module_path = ".".join(parts[:i])
            func_path = ".".join(parts[i:])
            if module_path in self.known_modules:
                return f"{module_path}.{func_path}"
            # Also check if the prefix matches an alias (for partial chains)
            if module_path in self.alias_to_module:
                full_module = self.alias_to_module[module_path]
                return f"{full_module}.{func_path}"
        return None


# ── Instance variable tracker ────────────────────────────────────────

class _InstanceTracker:
    """Tracks variable-to-class-type mappings for instance method resolution.

    Three scopes, resolved in order:
      1. **Function-local** — ``x = Class()`` inside a function body
      2. **Module-level** — ``x = Class()`` at module top level
      3. **Self-attribute** — ``self.x = Class()`` inside ``__init__``
    """

    def __init__(self) -> None:
        # Module-level: var_name → class_name
        self.module_vars: dict[str, str] = {}
        # Function-local: var_name → class_name (reset per function)
        self.local_vars: dict[str, str] = {}
        # Self-attrs per class: class_name → {attr_name → target_class}
        self.self_attrs: dict[str, dict[str, str]] = {}

    def set_module_var(self, var_name: str, class_name: str) -> None:
        self.module_vars[var_name] = class_name

    def set_local_var(self, var_name: str, class_name: str) -> None:
        self.local_vars[var_name] = class_name

    def set_self_attr(self, parent_class: str, attr_name: str, target_class: str) -> None:
        if parent_class not in self.self_attrs:
            self.self_attrs[parent_class] = {}
        self.self_attrs[parent_class][attr_name] = target_class

    def resolve_instance(self, var_name: str) -> str | None:
        """Look up a variable name, checking local scope first, then module."""
        return self.local_vars.get(var_name) or self.module_vars.get(var_name)

    def get_self_attr(self, parent_class: str, attr_name: str) -> str | None:
        """Look up a self.attr → class mapping for a parent class."""
        if parent_class in self.self_attrs:
            return self.self_attrs[parent_class].get(attr_name)
        return None

    def clear_locals(self) -> None:
        self.local_vars.clear()


# ── File context ─────────────────────────────────────────────────────

class _FileContext:
    """Minimal symbol context for a single file."""

    def __init__(self, tree: ast.Module, source_path: Path,
                 rel_path: str | None = None) -> None:
        self.rel_path = rel_path or _rel_str(source_path)
        self.functions: set[str] = set()
        self.classes: set[str] = set()
        self.methods: dict[str, set[str]] = {}  # class_name -> method names
        self.current_class: str | None = None
        self.imports = _ImportResolver(_file_module(self.rel_path))

        self._build(tree)

    def _build(self, tree: ast.Module) -> None:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                self.functions.add(node.name)
            elif isinstance(node, ast.AsyncFunctionDef):
                self.functions.add(node.name)
            elif isinstance(node, ast.ClassDef):
                self.classes.add(node.name)
                self.methods[node.name] = set()
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.methods[node.name].add(item.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports.add_import(alias)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    self.imports.add_import_from(
                        alias, node.module, node.level)


# ── Public entry point ───────────────────────────────────────────────

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
    ctx = _FileContext(tree, source_path, rel_path=rel)

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
        self._func_stack: list[str] = []
        self._instance_tracker = _InstanceTracker()
        # Current function's parameter name → type_name (from type hints)
        self._current_param_types: dict[str, str] = {}

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

        # Save outer scope and set up fresh function-local tracking
        saved_param_types = self._current_param_types
        saved_locals = self._instance_tracker.local_vars
        self._current_param_types = {}
        self._instance_tracker.local_vars = {}

        # Collect parameter type hints: def f(param: ClassType, ...)
        all_args = list(node.args.args) + list(node.args.posonlyargs) + list(node.args.kwonlyargs)
        for arg in all_args:
            if arg.annotation:
                type_name = _extract_type_name(arg.annotation)
                if type_name:
                    self._current_param_types[arg.arg] = type_name

        self.generic_visit(node)

        # Restore outer scope
        self._current_param_types = saved_param_types
        self._instance_tracker.local_vars = saved_locals
        self._func_stack.pop()

    # ── assignment tracking ───────────────────────────────────────

    def _resolve_class_ref(self, name: str) -> str | None:
        """Resolve a class name to an identifier usable for method lookup.

        Returns:
          - ``"ClassName"`` for same-file classes
          - ``"external:full.module.ClassName"`` for imported classes
          - ``None`` if the name cannot be resolved to a known class
        """
        if name in self.ctx.classes:
            return name
        imported = self.ctx.imports.resolve_name(name)
        if imported:
            return f"external:{imported}"
        return None

    def _class_has_method(self, class_ref: str, method: str) -> bool:
        """Check whether a class (same-file or external) has a given method."""
        if class_ref.startswith("external:"):
            # External classes — we can't verify methods at extract time,
            # but we trust the import resolution was correct.
            return True
        return method in self.ctx.methods.get(class_ref, set())

    def _form_target(self, class_ref: str, method: str) -> str:
        """Build a target node ID for a method on a class reference."""
        if class_ref.startswith("external:"):
            qual = class_ref[len("external:"):]
            return f"external:{qual}.{method}"
        return f"{self.rel}::{class_ref}.{method}"

    def visit_Assign(self, node: ast.Assign) -> None:
        """Track ``x = ClassName()`` for instance method resolution."""
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            class_ref = self._resolve_class_ref(node.value.func.id)
            if class_ref:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        # x = Class()
                        if self._func_stack:
                            self._instance_tracker.set_local_var(target.id, class_ref)
                        else:
                            self._instance_tracker.set_module_var(target.id, class_ref)
                    elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                        # self.x = Class()
                        if self._class_stack:
                            self._instance_tracker.set_self_attr(
                                self._class_stack[-1], target.attr, class_ref)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Track annotated assignments: ``x: ClassType = ClassType()``."""
        if node.value and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            class_ref = self._resolve_class_ref(node.value.func.id)
            if class_ref and isinstance(node.target, ast.Name):
                if self._func_stack:
                    self._instance_tracker.set_local_var(node.target.id, class_ref)
                else:
                    self._instance_tracker.set_module_var(node.target.id, class_ref)
        self.generic_visit(node)

    # ── inheritance ────────────────────────────────────────────────

    def _process_inherits(self, node: ast.ClassDef) -> None:
        for base in node.bases:
            if isinstance(base, ast.Name):
                target_id = self._resolve_inherit_target(base.id)
                if target_id:
                    res = Resolution.same_file_exact
                    conf = get_confidence(res)
                    self.edges.append(GraphEdge(
                        id=self._next_edge_id(),
                        type=EdgeType.inherits,
                        source=f"{self.rel}::{node.name}",
                        target=target_id,
                        confidence=conf,
                        source_location=EdgeLocation(
                            file_path=self.rel,
                            line_start=node.lineno,
                            line_end=getattr(node, "end_lineno", node.lineno),
                        ),
                        metadata=EdgeMetadata(
                            call_expr=base.id,
                            resolution=res,
                            reason=f"Class `{node.name}` inherits from `{base.id}`.",
                            evidence={
                                "base_class": base.id,
                                "source_location": {
                                    "file_path": self.rel,
                                    "line_start": node.lineno,
                                },
                            },
                        ),
                    ))

    def _resolve_inherit_target(self, name: str) -> str:
        if name in self.ctx.functions or name in self.ctx.methods.get("", set()):
            return f"{self.rel}::{name}"
        target = self.ctx.imports.resolve_name(name)
        if target:
            return f"external:{target}"
        return f"external:{name}"

    # ── calls ──────────────────────────────────────────────────────

    def visit_Call(self, node: ast.Call) -> None:
        call_expr = resolve_call_name(node)
        source_id = self._current_function_id(node)

        target_id, resolution = self._resolve_call(node)

        if target_id:
            conf = get_confidence(resolution)
            reason = self._build_call_reason(resolution, call_expr, target_id)
            evidence = self._build_call_evidence(resolution, call_expr, target_id)
            self.edges.append(GraphEdge(
                id=self._next_edge_id(),
                type=EdgeType.calls,
                source=source_id or self.rel,
                target=target_id,
                confidence=conf,
                source_location=EdgeLocation(
                    file_path=self.rel,
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                ),
                metadata=EdgeMetadata(
                    call_expr=call_expr,
                    resolution=resolution,
                    reason=reason,
                    evidence=evidence,
                ),
            ))

        self.generic_visit(node)

    def _current_function_id(self, call_node: ast.Call) -> str | None:
        if not self._func_stack:
            return None
        func_name = self._func_stack[-1]
        current_class = self._class_stack[-1] if self._class_stack else None
        if current_class:
            return f"{self.rel}::{current_class}.{func_name}"
        return f"{self.rel}::{func_name}"

    def _resolve_call(self, node: ast.Call) -> tuple[str, Resolution]:
        """Try to resolve a Call node to a target node ID and resolution."""
        func = node.func

        if isinstance(func, ast.Name):
            return self._resolve_name_call(func.id)

        if isinstance(func, ast.Attribute):
            return self._resolve_attribute_call(func)

        return "", Resolution.unresolved

    def _build_call_reason(self, resolution: Resolution, call_expr: str | None,
                           target_id: str) -> str:
        """Generate a human-readable reason for this call edge."""
        expr = call_expr or "unknown"
        if resolution == Resolution.same_file_exact:
            return f"Direct call to same-file function `{expr}`."
        if resolution == Resolution.self_method_resolved:
            return f"Same-class method call `{expr}`."
        if resolution == Resolution.imported_function_exact:
            return f"Resolved `{expr}` via from-import."
        if resolution == Resolution.imported_function_alias:
            return f"Resolved `{expr}` via aliased from-import."
        if resolution == Resolution.imported_module_attribute:
            return f"Resolved `{expr}` via module attribute access."
        if resolution == Resolution.relative_import_resolved:
            return f"Resolved `{expr}` via relative import."
        if resolution == Resolution.parameter_type_hint_resolved:
            return f"Resolved `{expr}` via parameter type hint."
        if resolution == Resolution.local_instance_resolved:
            return f"Resolved `{expr}` via function-local instance variable."
        if resolution == Resolution.module_instance_resolved:
            return f"Resolved `{expr}` via module-level instance variable."
        if resolution == Resolution.constructor_call_resolved:
            return f"Resolved `{expr}` via constructor-chain call."
        if resolution == Resolution.self_attribute_instance_resolved:
            return f"Resolved `{expr}` via self.attr instance variable."
        if resolution == Resolution.external_symbol:
            return f"Unresolved external call `{expr}` — treated as third-party."
        if resolution == Resolution.unresolved:
            return f"Could not resolve `{expr}`."
        return f"Resolved `{expr}` (resolution: {resolution.value})."

    def _build_call_evidence(self, resolution: Resolution, call_expr: str | None,
                             target_id: str) -> dict:
        """Build evidence dict for this call edge."""
        evidence: dict = {
            "source_location": {
                "file_path": self.rel,
            },
        }
        if resolution == Resolution.imported_function_exact:
            evidence["import_resolution"] = "from-import exact name"
            evidence["matched_symbol_id"] = target_id
        elif resolution == Resolution.imported_function_alias:
            evidence["import_resolution"] = "from-import with alias"
            evidence["matched_symbol_id"] = target_id
        elif resolution == Resolution.imported_module_attribute:
            evidence["import_resolution"] = "module attribute access"
            evidence["matched_symbol_id"] = target_id
        elif resolution == Resolution.relative_import_resolved:
            evidence["import_resolution"] = "relative import"
            evidence["matched_symbol_id"] = target_id
        elif resolution == Resolution.self_method_resolved:
            evidence["resolution_method"] = "same-class self.method()"
            evidence["matched_symbol_id"] = target_id
        elif resolution == Resolution.same_file_exact:
            evidence["resolution_method"] = "same-file function"
            evidence["matched_symbol_id"] = target_id
        elif resolution == Resolution.external_symbol:
            evidence["resolution_method"] = "external / unresolved"
        if call_expr:
            evidence["call_expr"] = call_expr
        return evidence

    # ── name call resolution ───────────────────────────────────────

    def _resolve_name_call(self, name: str) -> tuple[str, Resolution]:
        """Resolve a plain name call: ``func()``."""
        current_class = self._class_stack[-1] if self._class_stack else None

        # Don't generate calls edges for class constructors like ``ClassName()``
        if name in self.ctx.classes:
            return "", Resolution.unresolved

        # Same-file top-level function
        if name in self.ctx.functions:
            return f"{self.rel}::{name}", Resolution.same_file_exact

        # Current class method (implicit self.method() without self prefix)
        if current_class and name in self.ctx.methods.get(current_class, set()):
            return f"{self.rel}::{current_class}.{name}", Resolution.self_method_resolved

        # Cross-file import — check if the name looks like a class (PascalCase heuristic)
        target = self.ctx.imports.resolve_name(name)
        if target:
            # Heuristic: PascalCase names are likely classes, not callable functions.
            # PEP 8: class names use CapWords convention.  Skip calls edges for them.
            if name[0].isupper():
                return "", Resolution.unresolved
            kind = self.ctx.imports.resolve_name_kind(name)
            return f"external:{target}", kind

        # Unresolved — treated as external symbol
        return f"external:{name}", Resolution.external_symbol

    # ── attribute call resolution ──────────────────────────────────

    def _resolve_attribute_call(self, node: ast.Attribute) -> tuple[str, Resolution]:
        """Resolve an attribute-style call like ``obj.method()`` or ``a.b.c.func()``.

        Resolution order (highest confidence first):
          1. self.method()                  → self_method_resolved (0.90)
          2. self.attr.method()             → self_attribute_instance_resolved (0.75)
          3. ClassName().method()          → constructor_call_resolved (0.75)
          4. param.method() (type hint)     → parameter_type_hint_resolved (0.82)
          5. x.method() (x = Class())       → local/module_instance_resolved (0.80/0.78)
          6. import_alias.method()          → imported_module_attribute (0.88)
          7. a.b.c.method() (chained)       → imported_module_attribute (0.88)
        """
        attr = node.attr
        value = node.value
        current_class = self._class_stack[-1] if self._class_stack else None

        # 1. self.method() — same-class method call
        if isinstance(value, ast.Name) and value.id == "self":
            if current_class and attr in self.ctx.methods.get(current_class, set()):
                return f"{self.rel}::{current_class}.{attr}", Resolution.self_method_resolved

        # 2. self.attr.method() — self attribute instance method call
        if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name) and value.value.id == "self":
            if current_class:
                self_attr = value.attr
                class_ref = self._instance_tracker.get_self_attr(current_class, self_attr)
                if class_ref and self._class_has_method(class_ref, attr):
                    return self._form_target(class_ref, attr), Resolution.self_attribute_instance_resolved

        # 3. Constructor chain: ClassName().method()
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            class_ref = self._resolve_class_ref(value.func.id)
            if class_ref and self._class_has_method(class_ref, attr):
                return self._form_target(class_ref, attr), Resolution.constructor_call_resolved

        # 4-5. Simple attribute: obj.method()
        if isinstance(value, ast.Name):
            obj_name = value.id

            # 4. Parameter type hint: param.method()
            if obj_name in self._current_param_types:
                type_name = self._current_param_types[obj_name]
                class_ref = self._resolve_class_ref(type_name)
                if class_ref and self._class_has_method(class_ref, attr):
                    return self._form_target(class_ref, attr), Resolution.parameter_type_hint_resolved

            # 5. Instance variable: x.method() where x = Class()
            class_ref = self._instance_tracker.resolve_instance(obj_name)
            if class_ref and self._class_has_method(class_ref, attr):
                # Determine scope: local vs module
                if obj_name in self._instance_tracker.local_vars:
                    kind = Resolution.local_instance_resolved
                else:
                    kind = Resolution.module_instance_resolved
                return self._form_target(class_ref, attr), kind

            # 6. Import alias: token_store.save_token()
            target = self.ctx.imports.resolve_attribute(obj_name, attr)
            if target:
                return f"external:{target}", Resolution.imported_module_attribute

        # 7. Chained attribute: a.b.c.func()
        full_chain = _reconstruct_attribute(node)
        target = self.ctx.imports.resolve_chained(full_chain)
        if target:
            return f"external:{target}", Resolution.imported_module_attribute

        return "", Resolution.unresolved
