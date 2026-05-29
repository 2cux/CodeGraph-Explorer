"""Symbol extraction from parsed AST nodes."""

import ast
import re
from pathlib import Path

from codegraph.graph.models import GraphNode, NodeType, Location, Resolution


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


def _is_test_file(rel_path: str) -> bool:
    """Check whether *rel_path* refers to a test file.

    Recognized patterns (per user spec):
    - ``tests/`` directory (any file inside)
    - ``test_`` prefix files (e.g. ``test_auth.py``)
    - ``_test`` suffix files (e.g. ``auth_test.py``)
    """
    normalized = rel_path.replace("\\", "/")
    parts = normalized.split("/")
    if "tests" in parts:
        return True
    filename = parts[-1]
    if filename.startswith("test_"):
        return True
    if filename.endswith("_test.py"):
        return True
    return False


def _is_test_class(cls_node: ast.ClassDef) -> bool:
    """Check if a class definition is a test class.

    Recognized patterns:
    - Class name starts with ``Test`` (e.g. ``TestAuth``)
    - Class inherits from ``unittest.TestCase``
    """
    if cls_node.name.startswith("Test"):
        return True
    for base in cls_node.bases:
        if isinstance(base, ast.Attribute):
            if base.attr == "TestCase":
                return True
        elif isinstance(base, ast.Name) and base.id == "TestCase":
            return True
    return False


# HTTP method names used by FastAPI decorators on router/app objects
_FASTAPI_HTTP_METHODS: frozenset[str] = frozenset({
    "get", "post", "put", "delete", "patch", "head", "options", "trace",
})


def _detect_route_decorator(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict | None:
    """Detect FastAPI / Flask / Django route decorators on a function.

    Returns a ``dict`` with ``framework``, ``method``, and ``path`` keys,
    or ``None`` if no route decorator is found.
    """
    for dec in fn.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        if not isinstance(dec.func, ast.Attribute):
            continue

        attr_name = dec.func.attr
        path = ""
        if dec.args and isinstance(dec.args[0], ast.Constant):
            path = str(dec.args[0].value)

        # FastAPI: @router.post("/path"), @app.get("/path"), etc.
        if attr_name in _FASTAPI_HTTP_METHODS:
            return {
                "framework": "fastapi",
                "method": attr_name.upper(),
                "path": path,
                "resolution": Resolution.fastapi_route_decorator.value,
                "reason": f"Function decorated with FastAPI @router.{attr_name}('{path}') — HTTP {attr_name.upper()} route handler.",
                "evidence": {
                    "decorator": f"@router.{attr_name}",
                    "route_path": path,
                    "http_method": attr_name.upper(),
                },
            }

        # Flask: @app.route("/path", methods=["POST"])
        if attr_name == "route":
            methods = ["ALL"]
            for kw in dec.keywords:
                if kw.arg == "methods" and isinstance(kw.value, ast.List):
                    methods = [
                        e.value.upper()
                        for e in kw.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ] or ["ALL"]
            return {
                "framework": "flask",
                "method": ",".join(methods),
                "path": path,
                "resolution": Resolution.flask_route_decorator.value,
                "reason": f"Function decorated with Flask @app.route('{path}') — HTTP route handler.",
                "evidence": {
                    "decorator": "@app.route",
                    "route_path": path,
                    "http_method": ",".join(methods),
                },
            }

    return None


def _detect_route_decorators_for_class(cls: ast.ClassDef) -> list[dict]:
    """Detect route-related decorators on a class (e.g. Django admin.register)."""
    results: list[dict] = []
    for dec in cls.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        if isinstance(dec.func, ast.Attribute) and dec.func.attr == "register":
            results.append({
                "framework": "django",
                "method": "ADMIN",
                "path": "",
                "resolution": Resolution.django_view_heuristic.value,
                "reason": "Class decorated with Django @admin.register — admin view.",
                "evidence": {"decorator": "@admin.register"},
            })
    return results


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


def _is_external_import(full_name: str, current_module: str) -> bool:
    """Heuristic to guess whether an import refers to a third-party package.

    Returns True if likely external (stdlib or third-party), False if likely
    project-internal.

    A dotted import whose first component matches the current file's
    top-level package is always internal. Single-component imports
    (e.g. ``os``, ``json``) are treated as external unless they match
    the current top-level package.
    """
    if not full_name:
        return False
    top = full_name.split(".")[0]
    current_top = current_module.split(".")[0] if current_module else ""
    # Same top-level package as current file → internal
    if top == current_top:
        return False
    # Common stdlib / well-known third-party top-levels → external
    if top in _STDLIB_TOP_LEVELS:
        return True
    # Single-component name that isn't the current package → likely external
    if "." not in full_name and top != current_top:
        return True
    return False


def _resolve_relative_module(base: str | None, level: int,
                             current_module: str) -> str:
    """Resolve a relative import to an absolute module path.

    E.g. for file module ``a.b.c``, level=1 base=``d`` → ``a.b.d``.
    """
    if level == 0:
        return base or ""
    parts = current_module.split(".")
    if level > len(parts):
        return base or ""
    parent = ".".join(parts[:-level])
    if base:
        return f"{parent}.{base}" if parent else base
    return parent


# Common stdlib top-level modules (not exhaustive, but covers the common cases).
_STDLIB_TOP_LEVELS: set[str] = {
    "os", "sys", "re", "json", "math", "random", "datetime", "time",
    "collections", "itertools", "functools", "typing", "io", "pathlib",
    "hashlib", "hmac", "base64", "struct", "secrets", "logging", "abc",
    "ast", "unittest", "subprocess", "threading", "asyncio", "enum",
    "dataclasses", "copy", "pprint", "textwrap", "string", "uuid",
    "tempfile", "shutil", "glob", "fnmatch", "traceback", "warnings",
    "inspect", "importlib", "pkgutil", "types", "typing_extensions",
    "concurrent", "urllib", "http", "email", "xml", "html", "csv",
    "sqlite3", "pickle", "gzip", "zipfile", "tarfile", "configparser",
    "argparse", "getopt", "ctypes", "atexit", "signal", "socket",
    "ssl", "select", "asyncore", "asynchat", "socketserver",
}


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
                is_external = _is_external_import(alias.name, module)
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
            level = imp.level
            for alias in imp.names:
                alias_name = alias.asname or alias.name
                # Resolve relative imports to absolute form for the qualified name
                if level > 0:
                    abs_base = _resolve_relative_module(base, level, module)
                    full_name = f"{abs_base}.{alias.name}" if abs_base else alias.name
                else:
                    full_name = f"{base}.{alias.name}" if base else alias.name
                is_external = _is_external_import(full_name, module) if not level > 0 else False
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
    is_test_class: bool = False,
) -> None:
    """Extract a function/method node and add it to the list."""
    is_test_fn = fn.name.startswith("test_") or fn.name == "test"

    if parent_class:
        symbol_name = f"{parent_class}.{fn.name}"
        # test_ methods inside Test* / unittest.TestCase classes → type=test
        if is_test_fn and is_test_class:
            node_type = NodeType.test
        else:
            node_type = NodeType.method
        qualified_name = f"{module}.{parent_class}.{fn.name}"
        display_name = f"{parent_class}.{fn.name}"
    else:
        symbol_name = fn.name
        node_type = NodeType.test if is_test_fn else NodeType.function
        qualified_name = f"{module}.{fn.name}"
        display_name = fn.name

    tags = ["async"] if isinstance(fn, ast.AsyncFunctionDef) else []
    if is_test_fn:
        tags.append("test")

    node_metadata: dict = {}
    route_info = _detect_route_decorator(fn)
    if route_info:
        node_metadata["route"] = {
            "framework": route_info.get("framework", ""),
            "method": route_info.get("method", ""),
            "path": route_info.get("path", ""),
        }
        node_metadata["detection_resolution"] = route_info.get("resolution", "")
        node_metadata["detection_reason"] = route_info.get("reason", "")
        node_metadata["detection_evidence"] = route_info.get("evidence", {})
        tags.append("route")
        tags.append("api")
        tags.append(route_info["framework"])

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
        metadata=node_metadata,
    ))


def _extract_class_fields(cls: ast.ClassDef) -> list[str]:
    """Extract field names from a class body (AnnAssign at class level)."""
    fields: list[str] = []
    for node in cls.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if not node.target.id.startswith("_"):
                fields.append(node.target.id)
    return fields


def _extract_type_name(annotation: ast.expr) -> str | None:
    """Extract a simple type name from an annotation node."""
    if isinstance(annotation, ast.Name):
        return annotation.id
    return None


def _extract_class(
    nodes: list[GraphNode],
    cls: ast.ClassDef,
    rel_path: str,
    module: str,
) -> None:
    """Extract a class node and its methods."""
    qualified_name = f"{module}.{cls.name}"
    tags: list[str] = []
    # Check for dataclass decorator
    for dec in cls.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "dataclass":
            tags.append("dataclass")
            break
        if isinstance(dec, ast.Attribute) and dec.attr == "dataclass":
            tags.append("dataclass")
            break

    test_class = _is_test_class(cls)
    if test_class:
        tags.append("test")

    cls_metadata: dict = {}
    route_decorators = _detect_route_decorators_for_class(cls)
    if route_decorators:
        rd = route_decorators[0]
        cls_metadata["route"] = {
            "framework": rd.get("framework", ""),
            "method": rd.get("method", ""),
            "path": rd.get("path", ""),
        }
        cls_metadata.setdefault("detection_resolution", rd.get("resolution", ""))
        cls_metadata.setdefault("detection_reason", rd.get("reason", ""))
        cls_metadata.setdefault("detection_evidence", rd.get("evidence", {}))
        tags.append("route")
        tags.append("api")
        tags.append("django")

    # ── Base-class-based detection ────────────────────────────────────
    for base in cls.bases:
        base_name = _extract_type_name(base)
        if base_name in ("BaseModel",):
            tags.append("model")
            cls_metadata["is_data_model"] = True
            cls_metadata["model_kind"] = "pydantic"
            cls_metadata["detection_resolution"] = Resolution.pydantic_model_detected.value
            cls_metadata["detection_reason"] = f"Class `{cls.name}` inherits from `pydantic.BaseModel` — data model."
            cls_metadata["detection_evidence"] = {"base_class": "BaseModel", "framework": "pydantic"}
            fields = _extract_class_fields(cls)
            if fields:
                cls_metadata["fields"] = fields
        elif base_name in ("BaseSettings",):
            tags.extend(["config", "settings"])
            cls_metadata["is_config"] = True
            cls_metadata["config_kind"] = "pydantic_settings"
            cls_metadata["detection_resolution"] = Resolution.config_class_detected.value
            cls_metadata["detection_reason"] = f"Class `{cls.name}` inherits from `pydantic_settings.BaseSettings` — configuration."
            cls_metadata["detection_evidence"] = {"base_class": "BaseSettings", "framework": "pydantic_settings"}
            fields = _extract_class_fields(cls)
            if fields:
                cls_metadata["fields"] = fields
        elif base_name in ("TypedDict",):
            tags.append("schema")
            cls_metadata["is_schema"] = True
            cls_metadata["schema_kind"] = "typed_dict"
            cls_metadata["detection_resolution"] = Resolution.pydantic_model_detected.value
            cls_metadata["detection_reason"] = f"Class `{cls.name}` is a `TypedDict` — typed schema."
            cls_metadata["detection_evidence"] = {"base_class": "TypedDict"}
        elif base_name in ("NamedTuple",):
            tags.append("model")
            cls_metadata["is_data_model"] = True
            cls_metadata["model_kind"] = "named_tuple"
            cls_metadata["detection_resolution"] = Resolution.pydantic_model_detected.value
            cls_metadata["detection_reason"] = f"Class `{cls.name}` is a `NamedTuple` — data model."
            cls_metadata["detection_evidence"] = {"base_class": "NamedTuple"}
        elif base_name in ("Enum", "IntEnum", "StrEnum"):
            tags.append("schema")
            cls_metadata["is_schema"] = True
            cls_metadata["schema_kind"] = "enum"
            cls_metadata["detection_resolution"] = Resolution.pydantic_model_detected.value
            cls_metadata["detection_reason"] = f"Class `{cls.name}` is an `Enum` — schema definition."
            cls_metadata["detection_evidence"] = {"base_class": base_name}

    # ── File-path-based detection ─────────────────────────────────────
    rel_lower = rel_path.lower()
    if "/models/" in f"/{rel_lower}" or rel_lower.startswith("models/"):
        if "model" not in tags:
            tags.append("model")
            cls_metadata.setdefault("detection_resolution", Resolution.file_path_match.value)
            cls_metadata.setdefault("detection_reason", f"File `{rel_path}` is in a `models/` directory.")
            cls_metadata.setdefault("detection_evidence", {"file_path": rel_path, "heuristic": "models_directory"})
        cls_metadata.setdefault("is_data_model", True)
    if "/schemas/" in f"/{rel_lower}" or rel_lower.startswith("schemas/"):
        if "schema" not in tags:
            tags.append("schema")
            cls_metadata.setdefault("detection_resolution", Resolution.file_path_match.value)
            cls_metadata.setdefault("detection_reason", f"File `{rel_path}` is in a `schemas/` directory.")
            cls_metadata.setdefault("detection_evidence", {"file_path": rel_path, "heuristic": "schemas_directory"})
        cls_metadata.setdefault("is_schema", True)
    if "/store/" in f"/{rel_lower}" or "/stores/" in f"/{rel_lower}" or "/repository/" in f"/{rel_lower}" or "/repositories/" in f"/{rel_lower}":
        if "store" not in tags:
            tags.append("store")
            cls_metadata.setdefault("detection_resolution", Resolution.store_name_match.value)
            cls_metadata.setdefault("detection_reason", f"File `{rel_path}` is in a `store/` or `repository/` directory.")
            cls_metadata.setdefault("detection_evidence", {"file_path": rel_path, "heuristic": "store_directory"})
        if "persistence" not in tags:
            tags.append("persistence")
        cls_metadata.setdefault("is_store", True)
    if rel_lower.endswith("config.py") or rel_lower.endswith("settings.py"):
        if "config" not in tags:
            tags.append("config")
            cls_metadata.setdefault("detection_resolution", Resolution.config_class_detected.value)
            cls_metadata.setdefault("detection_reason", f"File `{rel_path}` is a config/settings module by naming convention.")
            cls_metadata.setdefault("detection_evidence", {"file_path": rel_path, "heuristic": "config_file_name"})
        if "settings" not in tags:
            tags.append("settings")
        cls_metadata.setdefault("is_config", True)

    # ── Class-name-based detection (weaker signal, only if not caught above) ──
    name_lower = cls.name.lower()
    if "store" in name_lower or "repository" in name_lower:
        if "store" not in tags:
            tags.append("store")
            cls_metadata.setdefault("detection_resolution", Resolution.store_name_match.value)
            cls_metadata.setdefault("detection_reason", f"Class name `{cls.name}` contains 'store'/'repository' — likely persistence class.")
            cls_metadata.setdefault("detection_evidence", {"class_name": cls.name, "heuristic": "store_class_name"})
        if "persistence" not in tags:
            tags.append("persistence")
        cls_metadata.setdefault("is_store", True)
    if "config" in name_lower or "settings" in name_lower or "setting" in name_lower:
        if "config" not in tags:
            tags.append("config")
            cls_metadata.setdefault("detection_resolution", Resolution.config_class_detected.value)
            cls_metadata.setdefault("detection_reason", f"Class name `{cls.name}` contains 'config'/'settings' — likely configuration class.")
            cls_metadata.setdefault("detection_evidence", {"class_name": cls.name, "heuristic": "config_class_name"})
        if "settings" not in tags and ("settings" in name_lower or "setting" in name_lower):
            tags.append("settings")
        cls_metadata.setdefault("is_config", True)
    if "model" in name_lower or "schema" in name_lower:
        if "model" not in tags and "schema" not in tags:
            if "model" in name_lower:
                tags.append("model")
                cls_metadata.setdefault("detection_resolution", Resolution.pydantic_model_detected.value)
                cls_metadata.setdefault("detection_reason", f"Class name `{cls.name}` contains 'model' — likely data model class.")
                cls_metadata.setdefault("detection_evidence", {"class_name": cls.name, "heuristic": "model_class_name"})
                cls_metadata.setdefault("is_data_model", True)
            elif "schema" in name_lower:
                tags.append("schema")
                cls_metadata.setdefault("detection_resolution", Resolution.pydantic_model_detected.value)
                cls_metadata.setdefault("detection_reason", f"Class name `{cls.name}` contains 'schema' — likely schema class.")
                cls_metadata.setdefault("detection_evidence", {"class_name": cls.name, "heuristic": "schema_class_name"})
                cls_metadata.setdefault("is_schema", True)

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
        metadata=cls_metadata,
    ))

    # Methods
    for item in cls.body:
        if isinstance(item, ast.FunctionDef):
            _extract_function(nodes, item, rel_path, module, parent_class=cls.name,
                              is_test_class=test_class)
        elif isinstance(item, ast.AsyncFunctionDef):
            _extract_function(nodes, item, rel_path, module, parent_class=cls.name,
                              is_test_class=test_class)
