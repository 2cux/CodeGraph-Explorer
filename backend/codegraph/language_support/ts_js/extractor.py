"""TypeScript / JavaScript extractor — tree-sitter based.

Produces ``ExtractorResult`` with symbols, imports, exports, calls,
references, and diagnostics in the language-agnostic schema defined
by the ``LanguageExtractor`` interface.

Shared logic lives in ``BaseTSExtractor``.  ``TypeScriptExtractor``
and ``JavaScriptExtractor`` are thin subclasses that set the
``language_id`` and select the tree-sitter language name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codegraph.graph.models import (
    GraphNode,
    GraphEdge,
    NodeType,
    EdgeType,
    Resolution,
    EdgeMetadata,
    EdgeLocation,
    Location,
)
from codegraph.language_support.extractor import (
    LanguageExtractor,
    ExtractorResult,
    ImportInfo,
    ExportInfo,
    CallEdge,
    RefEdge,
    Diagnostic,
)
from codegraph.language_support.ts_js.parser import get_parser, TreeSitterParser
from codegraph.language_support.ts_js.frameworks import extract_frameworks

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tree-sitter node types for top-level declarations
FUNCTION_DECLARATION = "function_declaration"
ARROW_FUNCTION = "arrow_function"
CLASS_DECLARATION = "class_declaration"
METHOD_DEFINITION = "method_definition"
INTERFACE_DECLARATION = "interface_declaration"
TYPE_ALIAS_DECLARATION = "type_alias_declaration"
IMPORT_STATEMENT = "import_statement"
EXPORT_STATEMENT = "export_statement"
LEXICAL_DECLARATION = "lexical_declaration"
VARIABLE_DECLARATION = "variable_declaration"
CALL_EXPRESSION = "call_expression"
NEW_EXPRESSION = "new_expression"
MEMBER_EXPRESSION = "member_expression"
IDENTIFIER = "identifier"
PROGRAM = "program"

# Edge counter (shared across extractors for unique IDs)
_edge_counter: list[int] = [0]


def _next_edge_id() -> str:
    _edge_counter[0] += 1
    return f"edge_{_edge_counter[0]:06d}"


def _node_id(file_path: str, name: str) -> str:
    """Build a stable node ID like ``src/foo.ts::MyClass``."""
    return f"{file_path}::{name}"


def _rel_path(abs_path: str, project_root: str) -> str:
    """Convert an absolute path to a POSIX relative path."""
    try:
        rel = Path(abs_path).relative_to(project_root)
    except ValueError:
        rel = Path(abs_path)
    return rel.as_posix()


def _read_content(file_path: str, content: str | None = None) -> str:
    """Return file content, reading from disk if needed."""
    if content is not None:
        return content
    return Path(file_path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Base TS Extractor
# ---------------------------------------------------------------------------


class BaseTSExtractor(LanguageExtractor):
    """Shared extraction logic for TypeScript and JavaScript.

    Subclasses set ``language_id``.
    """

    language_id: str = "typescript"  # overridden by subclasses
    _parser: TreeSitterParser | None = None

    def __init__(self) -> None:
        self._parser = get_parser()

    # ── Public API ──────────────────────────────────────────────────────

    def extract(
        self,
        file_path: str,
        content: str | None = None,
        project_root: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> ExtractorResult:
        src = _read_content(file_path, content)
        rel = _rel_path(file_path, project_root) if project_root else file_path

        result = self._parser.parse(src, self.language_id, file_path=rel)
        diags = list(result.diagnostics)

        if not result.ok:
            return ExtractorResult(
                language_id=self.language_id,
                file_path=rel,
                symbols=[],
                diagnostics=diags,
            )

        root = result.root_node

        # 1 — Extract symbols
        symbols, method_map = self._extract_symbols(root, rel)

        # 2 — Extract imports
        imports = self._extract_imports(root, rel)

        # 3 — Extract framework-specific nodes/edges
        framework = extract_frameworks(
            rel=rel,
            src=src,
            symbols=symbols,
            imports=imports,
            language_id=self.language_id,
        )
        if framework.nodes:
            existing_ids = {s.id for s in symbols}
            for node in framework.nodes:
                if node.id not in existing_ids:
                    symbols.append(node)
                    existing_ids.add(node.id)

        # 4 — Extract exports
        exports = self._extract_exports(root, symbols, rel)

        # 5 — Extract calls (intra-file edges)
        calls = self._extract_calls(root, symbols, method_map, rel)

        # 6 — Extract references (non-call)
        references: list[RefEdge] = []

        # 7 — Build structural edges
        structural = self._build_structural_edges(symbols, rel, imports)

        # 8 — Collect additional diagnostics for unsupported syntax
        diags.extend(self._collect_unsupported_diags(root, rel))
        diags.extend(framework.diagnostics)

        # Set language_id and support_level on all symbols
        for s in symbols:
            s.language_id = self.language_id
            s.language = self.language_id
            s.metadata["support_level"] = "beta"

        result = ExtractorResult(
            language_id=self.language_id,
            file_path=rel,
            symbols=symbols,
            imports=imports,
            exports=exports,
            calls=calls,
            references=references,
            diagnostics=diags,
        )
        # Attach raw edges for the resolver (internal transport)
        result._raw_edges = structural + self._calls_to_edges(calls, symbols, rel) + framework.edges
        return result

    # ── Symbol extraction ───────────────────────────────────────────────

    def _extract_symbols(self, root: Any, rel: str) -> tuple[list[GraphNode], dict[str, str]]:
        """Walk the CST and produce ``GraphNode`` objects.

        Returns ``(symbols, method_map)`` where *method_map* maps
        ``node_id`` → ``class_name`` for method nodes.
        """
        nodes: list[GraphNode] = []
        method_map: dict[str, str] = {}

        # File node
        nodes.append(GraphNode(
            id=rel,
            type=NodeType.file,
            name=Path(rel).name,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
        ))

        # Module node
        module = rel.replace("/", ".").replace(".tsx", "").replace(".ts", "").replace(".jsx", "").replace(".js", "")
        nodes.append(GraphNode(
            id=f"module:{module}",
            type=NodeType.module,
            name=module,
            qualified_name=module,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
        ))

        seen_names: dict[str, int] = {}  # for dedup within file

        # Collect top-level children, unwrapping export_statement wrappers
        def _iter_top_level(parent: Any):
            for child in parent.children:
                if child.type == EXPORT_STATEMENT:
                    # export function/class/const/let/var/type/interface/default
                    yield from child.children
                else:
                    yield child

        for child in _iter_top_level(root):
            if child.type == FUNCTION_DECLARATION:
                node = self._make_function_node(child, rel, seen_names, is_method=False)
                if node:
                    nodes.append(node)

            elif child.type == CLASS_DECLARATION:
                class_node, methods = self._make_class_node(child, rel, seen_names)
                if class_node:
                    nodes.append(class_node)
                    for m_node in methods:
                        nodes.append(m_node)
                        method_map[m_node.id] = class_node.name

            elif child.type == INTERFACE_DECLARATION:
                node = self._make_interface_node(child, rel, seen_names)
                if node:
                    nodes.append(node)

            elif child.type == TYPE_ALIAS_DECLARATION:
                node = self._make_type_alias_node(child, rel, seen_names)
                if node:
                    nodes.append(node)

            elif child.type in (LEXICAL_DECLARATION, VARIABLE_DECLARATION):
                var_nodes, has_export = self._make_variable_nodes(child, rel, seen_names)
                for vn in var_nodes:
                    nodes.append(vn)

        return nodes, method_map

    def _get_child_text(self, node: Any, child_type: str) -> str | None:
        """Get the text of the first child of a given type."""
        for child in node.children:
            if child.type == child_type:
                return child.text.decode("utf-8") if hasattr(child, "text") else ""
        return None

    def _find_child(self, node: Any, child_type: str) -> Any | None:
        for child in node.children:
            if child.type == child_type:
                return child
        return None

    def _find_children(self, node: Any, child_type: str) -> list[Any]:
        return [c for c in node.children if c.type == child_type]

    def _make_function_node(
        self, func_node: Any, rel: str, seen: dict[str, int], is_method: bool = False
    ) -> GraphNode | None:
        name_node = self._find_child(func_node, IDENTIFIER)
        if name_node is None:
            return None
        name = self._text(name_node)
        if not name:
            return None

        seen[name] = seen.get(name, 0) + 1
        nid = _node_id(rel, name)

        # Detect arrow function
        is_arrow = func_node.type == ARROW_FUNCTION

        # Collect parameters for signature
        params_node = self._find_child(func_node, "formal_parameters")
        param_text = ""
        if params_node:
            param_text = self._text(params_node)

        sig = f"{'async ' if self._is_async(func_node) else ''}function {name}{param_text}"
        if is_arrow:
            sig = f"const {name} = {param_text} =>"

        ntype = NodeType.method if is_method else NodeType.function

        # Detect test
        tags: list[str] = []
        if name.startswith("test") or name.endswith("test") or name.startswith("it"):
            tags.append("test")
            ntype = NodeType.test

        return GraphNode(
            id=nid,
            type=ntype,
            name=name,
            qualified_name=f"{rel}::{name}",
            display_name=name,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
            location=Location(
                line_start=func_node.start_point[0] + 1,
                line_end=func_node.end_point[0] + 1,
            ),
            signature=sig,
            tags=tags,
            metadata={"support_level": "beta"},
        )

    def _make_class_node(
        self, class_node: Any, rel: str, seen: dict[str, int]
    ) -> tuple[GraphNode | None, list[GraphNode]]:
        name_node = self._find_child(class_node, IDENTIFIER) or self._find_child(class_node, "type_identifier")
        if name_node is None:
            return None, []
        name = self._text(name_node)
        seen[name] = seen.get(name, 0) + 1
        nid = _node_id(rel, name)

        class_graph = GraphNode(
            id=nid,
            type=NodeType.class_,
            name=name,
            qualified_name=f"{rel}::{name}",
            display_name=name,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
            location=Location(
                line_start=class_node.start_point[0] + 1,
                line_end=class_node.end_point[0] + 1,
            ),
            signature=f"class {name}",
            metadata={"support_level": "beta"},
        )

        methods: list[GraphNode] = []
        body = self._find_child(class_node, "class_body")
        if body:
            for child in body.children:
                if child.type == METHOD_DEFINITION:
                    m_name = self._get_child_text(child, "property_identifier")
                    if m_name is None:
                        m_name = self._get_child_text(child, IDENTIFIER) or ""
                    if m_name and m_name != "constructor":
                        m_id = _node_id(rel, f"{name}.{m_name}")
                        m_node = GraphNode(
                            id=m_id,
                            type=NodeType.method,
                            name=m_name,
                            qualified_name=f"{rel}::{name}.{m_name}",
                            display_name=f"{name}.{m_name}",
                            file_path=rel,
                            language_id=self.language_id,
                            language=self.language_id,
                            location=Location(
                                line_start=child.start_point[0] + 1,
                                line_end=child.end_point[0] + 1,
                            ),
                            signature=f"{'async ' if self._is_async(child) else ''}{name}.{m_name}()",
                            metadata={"support_level": "beta", "class_name": name},
                        )
                        methods.append(m_node)

        return class_graph, methods

    def _make_interface_node(self, n: Any, rel: str, seen: dict[str, int]) -> GraphNode | None:
        name_node = self._find_child(n, "type_identifier") or self._find_child(n, IDENTIFIER)
        if name_node is None:
            return None
        name = self._text(name_node)
        seen[name] = seen.get(name, 0) + 1
        nid = _node_id(rel, name)
        return GraphNode(
            id=nid,
            type=NodeType.class_,  # closest match — interface maps to class
            name=name,
            qualified_name=f"{rel}::{name}",
            display_name=name,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
            location=Location(
                line_start=n.start_point[0] + 1,
                line_end=n.end_point[0] + 1,
            ),
            signature=f"interface {name}",
            tags=["interface"],
            metadata={"support_level": "beta", "ts_type": "interface"},
        )

    def _make_type_alias_node(self, n: Any, rel: str, seen: dict[str, int]) -> GraphNode | None:
        name_node = self._find_child(n, "type_identifier") or self._find_child(n, IDENTIFIER)
        if name_node is None:
            return None
        name = self._text(name_node)
        seen[name] = seen.get(name, 0) + 1
        nid = _node_id(rel, name)
        return GraphNode(
            id=nid,
            type=NodeType.function,  # closest match — type maps to variable-like
            name=name,
            qualified_name=f"{rel}::{name}",
            display_name=name,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
            location=Location(
                line_start=n.start_point[0] + 1,
                line_end=n.end_point[0] + 1,
            ),
            signature=f"type {name}",
            tags=["type_alias"],
            metadata={"support_level": "beta", "ts_type": "type_alias"},
        )

    def _make_variable_nodes(
        self, n: Any, rel: str, seen: dict[str, int]
    ) -> tuple[list[GraphNode], bool]:
        """Extract variable/constant declarations, detecting arrow functions.

        Returns ``(nodes, has_export_modifier)``.
        """
        nodes: list[GraphNode] = []
        has_export = self._has_export_modifier(n)

        for vd in self._find_children_recursive(n, "variable_declarator"):
            name_node = self._find_child(vd, IDENTIFIER)
            if name_node is None:
                continue
            name = self._text(name_node)
            if not name:
                continue

            value = self._find_child(vd, ARROW_FUNCTION)
            if value is None:
                value = self._find_child(vd, "function_expression")

            seen[name] = seen.get(name, 0) + 1
            nid = _node_id(rel, name)

            if value is not None:
                # Arrow function assigned to const
                params = self._find_child(value, "formal_parameters")
                param_text = self._text(params) if params else "()"
                ntype = NodeType.function
                sig = f"const {name} = {param_text} =>"
                tags: list[str] = []
                if name.startswith("test") or name.startswith("it"):
                    tags.append("test")
                    ntype = NodeType.test
                nodes.append(GraphNode(
                    id=nid, type=ntype, name=name,
                    qualified_name=f"{rel}::{name}",
                    display_name=name, file_path=rel,
                    language_id=self.language_id, language=self.language_id,
                    location=Location(
                        line_start=vd.start_point[0] + 1,
                        line_end=vd.end_point[0] + 1,
                    ),
                    signature=sig, tags=tags,
                    metadata={"support_level": "beta", "is_arrow": True},
                ))
            else:
                # Variable / constant
                nodes.append(GraphNode(
                    id=nid,
                    type=NodeType.function,  # variable
                    name=name,
                    qualified_name=f"{rel}::{name}",
                    display_name=name,
                    file_path=rel,
                    language_id=self.language_id,
                    language=self.language_id,
                    location=Location(
                        line_start=vd.start_point[0] + 1,
                        line_end=vd.end_point[0] + 1,
                    ),
                    signature=f"const {name}",
                    metadata={"support_level": "beta", "is_constant": True},
                ))

        return nodes, has_export

    # ── Import extraction ───────────────────────────────────────────────

    def _extract_imports(self, root: Any, rel: str) -> list[ImportInfo]:
        """Extract all import statements from the CST."""
        imports: list[ImportInfo] = []
        for child in root.children:
            if child.type == IMPORT_STATEMENT:
                imports.extend(self._parse_import_statement(child, rel))
            elif child.type == LEXICAL_DECLARATION:
                # Check for require() calls in variable declarations
                imports.extend(self._extract_require_imports(child, rel))
        return imports

    def _parse_import_statement(self, node: Any, rel: str) -> list[ImportInfo]:
        """Parse a single ``import`` statement node."""
        results: list[ImportInfo] = []
        line = node.start_point[0] + 1

        # Extract the module specifier (from "...")
        module_path = ""
        for child in node.children:
            if child.type == "string":
                module_path = self._text(child).strip("'\"")
                break

        if not module_path:
            return results

        is_external = not (module_path.startswith("./") or module_path.startswith("../"))

        # Collect import clauses
        import_clause = self._find_child(node, "import_clause")
        if import_clause is None:
            # Side-effect import: import "./x"
            results.append(ImportInfo(
                local_name="",
                module_path=module_path,
                imported_name="",
                is_external=is_external,
                line=line,
            ))
            return results

        # Named imports: import { foo, bar } from "./x"
        named_imports = self._find_child(import_clause, "named_imports")
        if named_imports:
            for spec in named_imports.children:
                if spec.type == "import_specifier":
                    local = self._get_child_text(spec, IDENTIFIER)
                    alias_node = self._find_child(spec, "property_identifier")
                    imported = self._text(alias_node) if alias_node else local
                    if local:
                        results.append(ImportInfo(
                            local_name=local,
                            module_path=module_path,
                            imported_name=imported or local,
                            is_external=is_external,
                            line=line,
                        ))

        # Namespace import: import * as foo from "./x"
        namespace_import = self._find_child(import_clause, "namespace_import")
        if namespace_import:
            ns_name = self._get_child_text(namespace_import, IDENTIFIER)
            if ns_name:
                results.append(ImportInfo(
                    local_name=ns_name,
                    module_path=module_path,
                    imported_name="*",
                    is_external=is_external,
                    line=line,
                ))

        # Default import: import foo from "./x"
        default = self._get_child_text(import_clause, IDENTIFIER)
        if default and not named_imports and not namespace_import:
            results.append(ImportInfo(
                local_name=default,
                module_path=module_path,
                imported_name="default",
                is_external=is_external,
                line=line,
            ))

        return results

    def _extract_require_imports(self, node: Any, rel: str) -> list[ImportInfo]:
        """Extract CommonJS ``require()`` calls from variable declarations.

        Handles both simple (``const x = require(...)``) and destructured
        (``const { a, b } = require(...)``) patterns.
        """
        results: list[ImportInfo] = []
        line = node.start_point[0] + 1

        for vd in self._find_children_recursive(node, "variable_declarator"):
            call = self._find_child(vd, CALL_EXPRESSION)
            if call is None:
                continue
            func = self._find_child(call, IDENTIFIER)
            if func is None or self._text(func) != "require":
                continue
            args_node = self._find_child(call, "arguments")
            if args_node is None:
                continue

            # Extract module path from require("...")
            module_path = ""
            for arg in args_node.children:
                if arg.type == "string":
                    module_path = self._text(arg).strip("'\"")
                    break
            if not module_path:
                continue

            is_external = not (module_path.startswith("./") or module_path.startswith("../"))

            # Simple pattern: const x = require(...)
            name_node = self._find_child(vd, IDENTIFIER)
            if name_node is not None:
                name = self._text(name_node)
                results.append(ImportInfo(
                    local_name=name,
                    module_path=module_path,
                    imported_name="default",
                    is_external=is_external,
                    line=line,
                ))
                continue

            # Destructured pattern: const { a, b } = require(...)
            obj_pattern = self._find_child(vd, "object_pattern")
            if obj_pattern is not None:
                for c in self._find_children_recursive(obj_pattern, IDENTIFIER):
                    name = self._text(c)
                    if name:
                        results.append(ImportInfo(
                            local_name=name,
                            module_path=module_path,
                            imported_name=name,
                            is_external=is_external,
                            line=line,
                        ))
                # Also check shorthand_property_identifier_pattern children
                for c in self._find_children_recursive(obj_pattern, "shorthand_property_identifier_pattern"):
                    name = self._text(c)
                    if name:
                        results.append(ImportInfo(
                            local_name=name,
                            module_path=module_path,
                            imported_name=name,
                            is_external=is_external,
                            line=line,
                        ))

        return results

    # ── Export extraction ───────────────────────────────────────────────

    def _extract_exports(self, root: Any, symbols: list[GraphNode], rel: str) -> list[ExportInfo]:
        """Extract export information from the CST."""
        exports: list[ExportInfo] = []
        symbol_names = {s.name: s.id for s in symbols}

        for child in root.children:
            if child.type == EXPORT_STATEMENT:
                exports.extend(self._parse_export_statement(child, symbol_names, rel))
            elif self._has_export_modifier(child):
                # Lexical/function with export modifier
                name_node = self._find_child(child, IDENTIFIER)
                if name_node is None:
                    # Check variable_declarator
                    for vd in self._find_children_recursive(child, "variable_declarator"):
                        vname = self._find_child(vd, IDENTIFIER)
                        if vname:
                            n = self._text(vname)
                            nid = symbol_names.get(n, _node_id(rel, n))
                            exports.append(ExportInfo(name=n, node_id=nid, is_default=False))
                else:
                    n = self._text(name_node)
                    nid = symbol_names.get(n, _node_id(rel, n))
                    exports.append(ExportInfo(name=n, node_id=nid, is_default=False))

            # Check for CommonJS module.exports / exports.foo
            exports.extend(self._extract_cjs_exports(child, rel))

        # Default export detection: export default function/class
        for child in root.children:
            if child.type == EXPORT_STATEMENT:
                default = self._find_child(child, "default")
                if default is not None:
                    # Find what's being default-exported
                    for c in child.children:
                        if c.type in (FUNCTION_DECLARATION, CLASS_DECLARATION):
                            dname = self._get_child_text(c, IDENTIFIER)
                            if dname:
                                nid = symbol_names.get(dname, _node_id(rel, dname))
                                exports.append(ExportInfo(name=dname, node_id=nid, is_default=True))

        return exports

    def _parse_export_statement(
        self, node: Any, symbol_names: dict[str, str], rel: str
    ) -> list[ExportInfo]:
        """Parse a single export statement node."""
        results: list[ExportInfo] = []

        # export * from "./x" — barrel export
        star = self._find_child(node, "*")
        if star:
            module_path = ""
            for child in node.children:
                if child.type == "string":
                    module_path = self._text(child).strip("'\"")
            results.append(ExportInfo(
                name="*",
                node_id=f"{rel}::barrel_export",
                is_default=False,
            ))
            return results

        # export { foo, bar } from "./x"
        export_clause = self._find_child(node, "export_clause")
        if export_clause:
            for spec in export_clause.children:
                if spec.type == "export_specifier":
                    local = self._get_child_text(spec, IDENTIFIER)
                    alias_node = self._find_child(spec, "property_identifier")
                    exported_name = self._text(alias_node) if alias_node else local
                    if local:
                        nid = symbol_names.get(local, _node_id(rel, local))
                        results.append(ExportInfo(name=local, node_id=nid, is_default=False))

        # Named exports from declaration
        for child in node.children:
            if child.type in (FUNCTION_DECLARATION, CLASS_DECLARATION):
                dname = self._get_child_text(child, IDENTIFIER)
                if dname:
                    nid = symbol_names.get(dname, _node_id(rel, dname))
                    results.append(ExportInfo(name=dname, node_id=nid, is_default=False))

        return results

    def _extract_cjs_exports(self, node: Any, rel: str) -> list[ExportInfo]:
        """Detect CommonJS ``module.exports =`` and ``exports.foo =`` patterns."""
        results: list[ExportInfo] = []
        if node.type != "expression_statement":
            return results

        # Walk into member expressions
        text = self._text(node) if hasattr(node, "text") else ""
        # module.exports = x
        if "module.exports" in text:
            for child in node.children:
                if child.type == "assignment_expression":
                    left = self._find_child(child, MEMBER_EXPRESSION)
                    if left and "module.exports" in self._text(left):
                        results.append(ExportInfo(
                            name="module_exports",
                            node_id=f"{rel}::module_exports",
                            is_default=True,
                        ))
        # exports.foo = x
        if "exports." in text:
            for child in node.children:
                if child.type == "assignment_expression":
                    left = self._find_child(child, MEMBER_EXPRESSION)
                    if left:
                        left_text = self._text(left)
                        if left_text.startswith("exports."):
                            export_name = left_text.split(".", 1)[1] if "." in left_text else left_text
                            results.append(ExportInfo(
                                name=export_name,
                                node_id=_node_id(rel, export_name),
                                is_default=False,
                            ))

        return results

    # ── Call extraction ─────────────────────────────────────────────────

    def _extract_calls(
        self, root: Any, symbols: list[GraphNode], method_map: dict[str, str], rel: str
    ) -> list[CallEdge]:
        """Extract intra-file call edges from the CST."""
        calls: list[CallEdge] = []
        symbol_names = {s.name: s.id for s in symbols}
        # Build a set of method names per class
        class_methods: dict[str, set[str]] = {}
        for s in symbols:
            if s.type == NodeType.method and "class_name" in s.metadata:
                cn = s.metadata["class_name"]
                class_methods.setdefault(cn, set()).add(s.name)

        self._walk_calls(root, calls, rel, symbol_names, class_methods, method_map)
        return calls

    def _walk_calls(
        self,
        node: Any,
        calls: list[CallEdge],
        rel: str,
        symbol_names: dict[str, str],
        class_methods: dict[str, set[str]],
        method_map: dict[str, str],
        parent_func: str | None = None,
    ) -> None:
        """Recursively walk CST to find call expressions."""
        for child in node.children:
            if child.type == CALL_EXPRESSION:
                call_info = self._resolve_call(
                    child, rel, symbol_names, class_methods, method_map,
                )
                if call_info:
                    calls.append(call_info)
            self._walk_calls(child, calls, rel, symbol_names, class_methods, method_map)

    def _resolve_call(
        self,
        call_node: Any,
        rel: str,
        symbol_names: dict[str, str],
        class_methods: dict[str, set[str]],
        method_map: dict[str, str],
    ) -> CallEdge | None:
        """Resolve a single call expression node."""
        line = call_node.start_point[0] + 1
        fn = call_node.children[0] if call_node.children else None
        if fn is None:
            return None

        # Simple function call: foo()
        if fn.type == IDENTIFIER:
            name = self._text(fn)
            if not name:
                return None
            return CallEdge(
                source_node_id="",
                target_expression=name,
                target_qualified_name=name,
                line=line,
                call_expr=f"{name}()",
                is_dynamic=False,
            )

        # new Foo() — constructor call
        if fn.type == NEW_EXPRESSION:
            cls_name = self._find_child_identifier(fn)
            if cls_name:
                return CallEdge(
                    source_node_id="",
                    target_expression=cls_name,
                    target_qualified_name=cls_name,
                    line=line,
                    call_expr=f"new {cls_name}()",
                    is_dynamic=False,
                )

        # Member expression: obj.method(), this.method(), imported.func()
        if fn.type == MEMBER_EXPRESSION:
            obj = fn.children[0] if fn.children else None
            # The property is the last child (skipping any "." tokens)
            prop = None
            for c in reversed(fn.children):
                if c.type in ("property_identifier", IDENTIFIER):
                    prop = c
                    break
            if obj is None or prop is None:
                return None

            obj_text = self._text(obj)
            prop_text = self._text(prop)

            # this.method()
            if obj_text == "this":
                return CallEdge(
                    source_node_id="",
                    target_expression=f"this.{prop_text}",
                    target_qualified_name=f"this.{prop_text}",
                    line=line,
                    call_expr=f"this.{prop_text}()",
                    is_dynamic=False,
                )

            # obj.method() — object is unknown type
            # Mark as pending cross-file resolution
            return CallEdge(
                source_node_id="",
                target_expression=f"{obj_text}.{prop_text}",
                target_qualified_name=f"{obj_text}.{prop_text}",
                line=line,
                call_expr=f"{obj_text}.{prop_text}()",
                is_dynamic=not obj_text.isidentifier(),
            )

        return None

    def _find_child_identifier(self, node: Any) -> str | None:
        """Find the first identifier in a node's children."""
        for child in node.children:
            if child.type == IDENTIFIER:
                return self._text(child)
            found = self._find_child_identifier(child)
            if found:
                return found
        return None

    # ── Structural edges ────────────────────────────────────────────────

    def _build_structural_edges(
        self, symbols: list[GraphNode], rel: str, imports: list[ImportInfo]
    ) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        file_id = rel
        module_id = f"module:{rel.replace('/', '.').replace('.tsx','').replace('.ts','').replace('.jsx','').replace('.js','')}"

        for s in symbols:
            if s.type == NodeType.file or s.type == NodeType.module:
                continue
            # contains: file → symbol
            edges.append(GraphEdge(
                id=_next_edge_id(),
                type=EdgeType.contains,
                source=file_id,
                target=s.id,
                confidence=1.0,
                source_location=EdgeLocation(
                    file_path=rel,
                    line_start=s.location.line_start if s.location else 0,
                    line_end=s.location.line_end if s.location else 0,
                ),
                metadata=EdgeMetadata(
                    resolution=Resolution.exact_ast_match,
                    provenance="ast",
                    reason=f"symbol defined in file",
                ),
            ))
            # defined_in: symbol → module
            edges.append(GraphEdge(
                id=_next_edge_id(),
                type=EdgeType.defined_in,
                source=s.id,
                target=module_id,
                confidence=1.0,
                source_location=EdgeLocation(
                    file_path=rel,
                    line_start=s.location.line_start if s.location else 0,
                    line_end=s.location.line_end if s.location else 0,
                ),
                metadata=EdgeMetadata(
                    resolution=Resolution.exact_ast_match,
                    provenance="ast",
                    reason=f"symbol defined in module",
                ),
            ))

        # imports edges
        for imp in imports:
            if not imp.local_name:
                continue
            # Find the symbol node for this import
            for s in symbols:
                if s.name == imp.local_name and s.type == NodeType.import_:
                    target = f"external:{imp.module_path}.{imp.imported_name}" if imp.is_external else _node_id(imp.module_path.replace("./", "").replace("../", ""), imp.imported_name)
                    edges.append(GraphEdge(
                        id=_next_edge_id(),
                        type=EdgeType.imports,
                        source=s.id,
                        target=target,
                        confidence=0.90 if not imp.is_external else 0.50,
                        source_location=EdgeLocation(
                            file_path=rel,
                            line_start=imp.line,
                            line_end=imp.line,
                        ),
                        metadata=EdgeMetadata(
                            resolution=Resolution.imported_function_exact if not imp.is_external else Resolution.package_external,
                            provenance="ast",
                            reason=f"import '{imp.local_name}' from '{imp.module_path}'",
                        ),
                    ))

        return edges

    def _calls_to_edges(
        self, calls: list[CallEdge], symbols: list[GraphNode], rel: str
    ) -> list[GraphEdge]:
        """Convert ``CallEdge`` structs to ``GraphEdge`` objects.

        Used for intra-file calls where both source and target are known.
        """
        edges: list[GraphEdge] = []
        symbol_by_name = {s.name: s.id for s in symbols}

        for c in calls:
            expr = c.target_expression
            # Try to find target in same file
            target_id = symbol_by_name.get(expr)
            resolution = Resolution.same_file_exact if target_id else Resolution.name_match_candidate
            confidence = 0.95 if target_id else 0.35

            if target_id is None:
                # Try this.method pattern
                if expr.startswith("this."):
                    method_name = expr[5:]
                    resolution = Resolution.this_method_exact
                    # Find matching method symbol
                    for s in symbols:
                        if s.name == method_name and s.type == NodeType.method:
                            target_id = s.id
                            confidence = 0.90
                            break

            edges.append(GraphEdge(
                id=_next_edge_id(),
                type=EdgeType.calls,
                source="",  # will be set by resolver
                target=target_id or f"unresolved:{expr}",
                confidence=confidence,
                source_location=EdgeLocation(
                    file_path=rel,
                    line_start=c.line,
                    line_end=c.line,
                ),
                metadata=EdgeMetadata(
                    resolution=resolution,
                    provenance="ast",
                    call_expr=c.call_expr,
                    reason=f"call to '{expr}'",
                ),
            ))

        return edges

    # ── Helpers ─────────────────────────────────────────────────────────

    def _text(self, node: Any) -> str:
        """Safely get the text of a tree-sitter node."""
        if node is None:
            return ""
        try:
            return node.text.decode("utf-8") if hasattr(node, "text") else ""
        except Exception:
            return ""

    def _is_async(self, node: Any) -> bool:
        for child in node.children:
            if child.type == "async":
                return True
        return False

    def _has_export_modifier(self, node: Any) -> bool:
        """Check if a declaration node has an ``export`` modifier."""
        for child in node.children:
            if child.type == "export":
                return True
        # Check parent for export
        parent = getattr(node, "parent", None)
        if parent is not None:
            for c in parent.children:
                if c.type == "export" and c.prev_sibling == node:
                    return True
        return False

    def _find_children_recursive(self, node: Any, child_type: str) -> list[Any]:
        """Recursively find all children of a given type."""
        results: list[Any] = []
        for child in node.children:
            if child.type == child_type:
                results.append(child)
            results.extend(self._find_children_recursive(child, child_type))
        return results

    def _collect_unsupported_diags(self, root: Any, rel: str) -> list[Diagnostic]:
        """Warn about unsupported syntax patterns."""
        diags: list[Diagnostic] = []
        for child in self._find_children_recursive(root, "jsx_element"):
            # JSX is expected in .tsx/.jsx — just note it
            if rel.endswith((".tsx", ".jsx")):
                break
            diags.append(Diagnostic(
                level="info",
                message="JSX detected in non-JSX file",
                file_path=rel,
                line=child.start_point[0] + 1,
            ))
            break
        return diags


# ---------------------------------------------------------------------------
# Concrete extractors
# ---------------------------------------------------------------------------


class TypeScriptExtractor(BaseTSExtractor):
    """TypeScript file extractor (.ts, .tsx)."""
    language_id = "typescript"


class JavaScriptExtractor(BaseTSExtractor):
    """JavaScript file extractor (.js, .jsx, .mjs, .cjs)."""
    language_id = "javascript"
