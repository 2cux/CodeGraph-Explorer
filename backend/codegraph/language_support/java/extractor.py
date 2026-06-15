"""Java extractor — tree-sitter based.

Produces ``ExtractorResult`` with symbols, imports, calls, references,
and diagnostics for Java source files.

Supports:
- package, class, interface, enum, method, constructor, field
- import declarations
- method calls, constructor calls, this/super/static calls
- extends, implements references
- annotation references
"""

from __future__ import annotations

import hashlib
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
from codegraph.language_support.java.parser import get_parser, JavaParser
from codegraph.language_support.java.frameworks import extract_spring

# ---------------------------------------------------------------------------
# Tree-sitter node type constants
# ---------------------------------------------------------------------------

PROGRAM = "program"
PACKAGE_DECLARATION = "package_declaration"
IMPORT_DECLARATION = "import_declaration"
CLASS_DECLARATION = "class_declaration"
INTERFACE_DECLARATION = "interface_declaration"
ENUM_DECLARATION = "enum_declaration"
ANNOTATION_TYPE_DECLARATION = "annotation_type_declaration"
METHOD_DECLARATION = "method_declaration"
CONSTRUCTOR_DECLARATION = "constructor_declaration"
FIELD_DECLARATION = "field_declaration"
VARIABLE_DECLARATOR = "variable_declarator"
METHOD_INVOCATION = "method_invocation"
OBJECT_CREATION_EXPRESSION = "object_creation_expression"
IDENTIFIER = "identifier"
TYPE_IDENTIFIER = "type_identifier"
STRING_LITERAL = "string_literal"
BLOCK_COMMENT = "block_comment"
LINE_COMMENT = "line_comment"
MARKER_ANNOTATION = "marker_annotation"
ANNOTATION = "annotation"
FORMAL_PARAMETERS = "formal_parameters"
MODIFIERS = "modifiers"
SUPERCLASS = "superclass"
SUPER_INTERFACES = "super_interfaces"
INTERFACE_TYPE_LIST = "interface_type_list"
ENUM_BODY = "enum_body"
ENUM_CONSTANT = "enum_constant"
CLASS_BODY = "class_body"
INTERFACE_BODY = "interface_body"
BLOCK = "block"
LOCAL_VARIABLE_DECLARATION = "local_variable_declaration"
ENHANCED_FOR_STATEMENT = "enhanced_for_statement"
RETURN_STATEMENT = "return_statement"
EXPRESSION_STATEMENT = "expression_statement"

# Edge counter
_edge_counter: list[int] = [0]


def _next_edge_id() -> str:
    _edge_counter[0] += 1
    return f"edge_{_edge_counter[0]:06d}"


def _node_id(file_path: str, name: str) -> str:
    return f"{file_path}::{name}"


def _rel_path(abs_path: str, project_root: str) -> str:
    try:
        rel = Path(abs_path).relative_to(project_root)
    except ValueError:
        rel = Path(abs_path)
    return rel.as_posix()


def _read_content(file_path: str, content: str | None = None) -> str:
    if content is not None:
        return content
    return Path(file_path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Java Extractor
# ---------------------------------------------------------------------------


class JavaExtractor(LanguageExtractor):
    """Java source file extractor (.java).

    Uses tree-sitter to parse Java source and extract symbols,
    imports, calls, references, and structural edges.
    """

    language_id: str = "java"
    _parser: JavaParser | None = None

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

        result = self._parser.parse(src, file_path=rel)
        diags = list(result.diagnostics)

        if not result.ok:
            return ExtractorResult(
                language_id=self.language_id,
                file_path=rel,
                symbols=[],
                diagnostics=diags,
            )

        root = result.root_node

        # 1 — Extract package declaration
        package_name = self._extract_package(root)

        # 2 — Extract imports
        imports = self._extract_imports(root, rel)

        # 3 — Extract symbols (classes, interfaces, enums, methods, fields)
        symbols = self._extract_symbols(root, rel, package_name)

        # 4 — Extract Spring framework nodes/edges
        framework = extract_spring(
            rel=rel,
            src=src,
            symbols=symbols,
            imports=imports,
        )
        if framework.nodes:
            existing_ids = {s.id for s in symbols}
            for node in framework.nodes:
                if node.id not in existing_ids:
                    symbols.append(node)
                    existing_ids.add(node.id)

        # 5 — Extract calls
        calls = self._extract_calls(root, symbols, rel)

        # 6 — Extract references (extends, implements, annotations)
        references = self._extract_references(root, symbols, rel)

        # 7 — Build structural edges
        structural = self._build_structural_edges(symbols, rel, imports, package_name)

        # 8 — Collect diagnostics
        diags.extend(self._collect_diagnostics(root, rel))
        diags.extend(framework.diagnostics)

        # Set language_id and support_level on all symbols
        for s in symbols:
            s.language_id = self.language_id
            s.language = self.language_id
            if "support_level" not in s.metadata:
                s.metadata["support_level"] = "beta"
                s.support_level = "beta"

        result = ExtractorResult(
            language_id=self.language_id,
            file_path=rel,
            symbols=symbols,
            imports=imports,
            exports=[],  # Java doesn't have explicit exports; public visibility is implicit
            calls=calls,
            references=references,
            diagnostics=diags,
        )
        result._raw_edges = structural + self._calls_to_edges(calls, rel) + framework.edges
        return result

    # ── Package extraction ──────────────────────────────────────────────

    def _extract_package(self, root: Any) -> str:
        """Extract package name from package declaration."""
        for child in root.children:
            if child.type == PACKAGE_DECLARATION:
                # Get the scoped identifier text
                for c in child.children:
                    if c.type in ("scoped_identifier", IDENTIFIER):
                        return self._text(c)
        return ""

    # ── Import extraction ──────────────────────────────────────────────

    def _extract_imports(self, root: Any, rel: str) -> list[ImportInfo]:
        """Extract import declarations."""
        imports: list[ImportInfo] = []
        for child in root.children:
            if child.type != IMPORT_DECLARATION:
                continue
            line = child.start_point[0] + 1
            is_static = False

            # Get the full import path
            for c in child.children:
                ctext = self._text(c)
                if c.type == "static":
                    is_static = True
                    continue
                if c.type in ("scoped_identifier", IDENTIFIER):
                    parts = ctext.rsplit(".", 1)
                    module_path = ".".join(ctext.split(".")[:-1]) if len(parts) > 1 else ""
                    if ctext.endswith(".*"):
                        # Wildcard import
                        imports.append(ImportInfo(
                            local_name="*",
                            module_path=ctext[:-2],
                            imported_name="*",
                            is_external=True,
                            line=line,
                        ))
                    else:
                        local_name = parts[-1]
                        imports.append(ImportInfo(
                            local_name=local_name,
                            module_path=module_path,
                            imported_name=local_name,
                            is_external=True,
                            line=line,
                        ))
                    break

        return imports

    # ── Symbol extraction ──────────────────────────────────────────────

    def _extract_symbols(
        self, root: Any, rel: str, package_name: str
    ) -> list[GraphNode]:
        """Walk the CST and produce GraphNode objects."""
        nodes: list[GraphNode] = []

        # File node
        nodes.append(GraphNode(
            id=rel,
            type=NodeType.file,
            name=Path(rel).name,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
        ))

        # Module node (package-based)
        module_name = package_name if package_name else Path(rel).stem
        nodes.append(GraphNode(
            id=f"module:{module_name}",
            type=NodeType.module,
            name=module_name,
            qualified_name=module_name,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
        ))

        # Package node
        if package_name:
            nodes.append(GraphNode(
                id=f"{rel}::package:{package_name}",
                type=NodeType.module,
                name=package_name,
                qualified_name=package_name,
                display_name=f"package {package_name}",
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                tags=["package"],
                support_level="beta",
                metadata={"support_level": "beta"},
            ))

        seen_names: dict[str, int] = {}

        for child in root.children:
            if child.type == CLASS_DECLARATION:
                class_nodes = self._make_class_node(child, rel, seen_names)
                nodes.extend(class_nodes)
            elif child.type == INTERFACE_DECLARATION:
                iface_node = self._make_interface_node(child, rel, seen_names)
                if iface_node:
                    nodes.append(iface_node)
            elif child.type == ENUM_DECLARATION:
                enum_nodes = self._make_enum_node(child, rel, seen_names)
                nodes.extend(enum_nodes)

        return nodes

    def _make_class_node(
        self, node: Any, rel: str, seen: dict[str, int]
    ) -> list[GraphNode]:
        """Extract a class declaration and its members."""
        nodes: list[GraphNode] = []

        name_node = self._find_child(node, IDENTIFIER)
        if name_node is None:
            return nodes
        name = self._text(name_node)
        seen[name] = seen.get(name, 0) + 1
        nid = _node_id(rel, name)

        # Detect annotations on this class
        annotations = self._extract_annotations(node)

        # Check for Spring stereotypes
        is_controller = any(a in annotations for a in ("RestController", "Controller"))
        is_service = "Service" in annotations
        is_repository = "Repository" in annotations
        is_component = "Component" in annotations

        tags: list[str] = []
        ntype = NodeType.class_
        if is_controller:
            ntype = NodeType.controller
            tags = ["controller", "spring"]
        elif is_service:
            ntype = NodeType.service
            tags = ["service", "spring"]
        elif is_repository:
            ntype = NodeType.service
            tags = ["repository", "spring"]
        elif is_component:
            ntype = NodeType.component
            tags = ["component", "spring"]

        # Detect extends / implements
        extends_name = None
        implements_list: list[str] = []
        for c in node.children:
            if c.type == SUPERCLASS:
                for sc in c.children:
                    if sc.type in (TYPE_IDENTIFIER, IDENTIFIER):
                        extends_name = self._text(sc)
            elif c.type == SUPER_INTERFACES:
                for sc in self._find_children(c, TYPE_IDENTIFIER):
                    implements_list.append(self._text(sc))

        sig_parts = [f"class {name}"]
        if extends_name:
            sig_parts.append(f"extends {extends_name}")
        if implements_list:
            sig_parts.append(f"implements {', '.join(implements_list)}")

        class_node = GraphNode(
            id=nid,
            type=ntype,
            name=name,
            qualified_name=f"{rel}::{name}",
            display_name=name,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
            framework_id="spring" if tags else None,
            location=Location(
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
            ),
            signature=" ".join(sig_parts),
            tags=tags,
            support_level="beta",
            metadata={
                "support_level": "beta",
                "extends": extends_name,
                "implements": implements_list,
                "annotations": annotations,
            },
        )
        nodes.append(class_node)

        # Extract methods, constructors, fields from class body
        body = self._find_child(node, CLASS_BODY)
        if body:
            for child in body.children:
                if child.type == METHOD_DECLARATION:
                    m_node = self._make_method_node(child, rel, name, seen)
                    if m_node:
                        nodes.append(m_node)
                elif child.type == CONSTRUCTOR_DECLARATION:
                    c_node = self._make_constructor_node(child, rel, name)
                    if c_node:
                        nodes.append(c_node)
                elif child.type == FIELD_DECLARATION:
                    f_nodes = self._make_field_nodes(child, rel, name, seen)
                    nodes.extend(f_nodes)

        return nodes

    def _make_interface_node(
        self, node: Any, rel: str, seen: dict[str, int]
    ) -> GraphNode | None:
        """Extract an interface declaration."""
        name_node = self._find_child(node, IDENTIFIER)
        if name_node is None:
            return None
        name = self._text(name_node)
        seen[name] = seen.get(name, 0) + 1
        nid = _node_id(rel, name)

        return GraphNode(
            id=nid,
            type=NodeType.class_,
            name=name,
            qualified_name=f"{rel}::{name}",
            display_name=name,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
            location=Location(
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
            ),
            signature=f"interface {name}",
            tags=["interface"],
            support_level="beta",
            metadata={"support_level": "beta", "java_type": "interface"},
        )

    def _make_enum_node(
        self, node: Any, rel: str, seen: dict[str, int]
    ) -> list[GraphNode]:
        """Extract an enum declaration."""
        nodes: list[GraphNode] = []
        name_node = self._find_child(node, IDENTIFIER)
        if name_node is None:
            return nodes
        name = self._text(name_node)
        seen[name] = seen.get(name, 0) + 1
        nid = _node_id(rel, name)

        nodes.append(GraphNode(
            id=nid,
            type=NodeType.class_,
            name=name,
            qualified_name=f"{rel}::{name}",
            display_name=name,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
            location=Location(
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
            ),
            signature=f"enum {name}",
            tags=["enum"],
            support_level="beta",
            metadata={"support_level": "beta", "java_type": "enum"},
        ))

        # Enum constants
        body = self._find_child(node, ENUM_BODY)
        if body:
            for child in body.children:
                if child.type == ENUM_CONSTANT:
                    const_name = self._get_child_text(child, IDENTIFIER)
                    if const_name:
                        nodes.append(GraphNode(
                            id=f"{nid}.{const_name}",
                            type=NodeType.function,
                            name=const_name,
                            qualified_name=f"{rel}::{name}.{const_name}",
                            display_name=f"{name}.{const_name}",
                            file_path=rel,
                            language_id=self.language_id,
                            language=self.language_id,
                            location=Location(
                                line_start=child.start_point[0] + 1,
                                line_end=child.end_point[0] + 1,
                            ),
                            signature=f"{name}.{const_name}",
                            tags=["enum_constant"],
                            support_level="beta",
                            metadata={"support_level": "beta", "class_name": name},
                        ))

        return nodes

    def _make_method_node(
        self, node: Any, rel: str, class_name: str, seen: dict[str, int]
    ) -> GraphNode | None:
        """Extract a method declaration."""
        name_node = self._find_child(node, IDENTIFIER)
        if name_node is None:
            return None
        name = self._text(name_node)
        seen[f"{class_name}.{name}"] = seen.get(f"{class_name}.{name}", 0) + 1
        nid = _node_id(rel, f"{class_name}.{name}")

        annotations = self._extract_annotations(node)

        # Collect parameters for signature
        params_node = self._find_child(node, FORMAL_PARAMETERS)
        param_text = self._text(params_node) if params_node else "()"

        tags: list[str] = []
        if annotations:
            tags.extend(annotations)

        return GraphNode(
            id=nid,
            type=NodeType.method,
            name=name,
            qualified_name=f"{rel}::{class_name}.{name}",
            display_name=f"{class_name}.{name}",
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
            location=Location(
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
            ),
            signature=f"{class_name}.{name}{param_text}",
            tags=tags,
            support_level="beta",
            metadata={
                "support_level": "beta",
                "class_name": class_name,
                "annotations": annotations,
            },
        )

    def _make_constructor_node(
        self, node: Any, rel: str, class_name: str
    ) -> GraphNode | None:
        """Extract a constructor declaration."""
        nid = _node_id(rel, f"{class_name}.{class_name}")

        params_node = self._find_child(node, FORMAL_PARAMETERS)
        param_text = self._text(params_node) if params_node else "()"

        annotations = self._extract_annotations(node)

        body_node = self._find_child(node, "constructor_body")
        body_text = self._text(body_node) if body_node else "{}"

        return GraphNode(
            id=nid,
            type=NodeType.method,
            name=class_name,
            qualified_name=f"{rel}::{class_name}.{class_name}",
            display_name=f"{class_name}.{class_name}()",
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
            location=Location(
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
            ),
            signature=f"{class_name}{param_text}",
            tags=["constructor"] + annotations,
            support_level="beta",
            metadata={
                "support_level": "beta",
                "class_name": class_name,
                "is_constructor": True,
                "annotations": annotations,
            },
        )

    def _make_field_nodes(
        self, node: Any, rel: str, class_name: str, seen: dict[str, int]
    ) -> list[GraphNode]:
        """Extract field declarations."""
        nodes: list[GraphNode] = []
        annotations = self._extract_annotations(node)

        for vd in self._find_children_recursive(node, VARIABLE_DECLARATOR):
            name_node = self._find_child(vd, IDENTIFIER)
            if name_node is None:
                continue
            name = self._text(name_node)
            seen[f"{class_name}.{name}"] = seen.get(f"{class_name}.{name}", 0) + 1
            nid = _node_id(rel, f"{class_name}.{name}")

            nodes.append(GraphNode(
                id=nid,
                type=NodeType.function,  # field maps to variable-like
                name=name,
                qualified_name=f"{rel}::{class_name}.{name}",
                display_name=f"{class_name}.{name}",
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(
                    line_start=vd.start_point[0] + 1,
                    line_end=vd.end_point[0] + 1,
                ),
                signature=f"{class_name}.{name}",
                tags=["field"] + annotations,
                support_level="beta",
                metadata={
                    "support_level": "beta",
                    "class_name": class_name,
                    "is_field": True,
                },
            ))

        return nodes

    # ── Annotation extraction ──────────────────────────────────────────

    def _extract_annotations(self, node: Any) -> list[str]:
        """Extract annotation names from a node's modifiers/children."""
        annotations: list[str] = []
        for child in node.children:
            if child.type == MODIFIERS:
                for mod_child in child.children:
                    if mod_child.type in (MARKER_ANNOTATION, ANNOTATION):
                        name = self._get_child_text(mod_child, IDENTIFIER)
                        if name:
                            annotations.append(name)
                    elif mod_child.type == ANNOTATION:
                        name = self._get_child_text(mod_child, IDENTIFIER)
                        if name:
                            annotations.append(name)
            elif child.type in (MARKER_ANNOTATION, ANNOTATION):
                name = self._get_child_text(child, IDENTIFIER)
                if name:
                    annotations.append(name)
        return annotations

    # ── Call extraction ────────────────────────────────────────────────

    def _extract_calls(
        self, root: Any, symbols: list[GraphNode], rel: str
    ) -> list[CallEdge]:
        """Extract method invocation and constructor call edges."""
        calls: list[CallEdge] = []
        symbol_names = {s.name: s.id for s in symbols}
        # Build set of method names by class
        class_methods: dict[str, set[str]] = {}
        for s in symbols:
            if s.type == NodeType.method and "class_name" in s.metadata:
                cn = s.metadata["class_name"]
                class_methods.setdefault(cn, set()).add(s.name)

        self._walk_for_calls(root, calls, rel, symbol_names, class_methods)
        return calls

    def _walk_for_calls(
        self,
        node: Any,
        calls: list[CallEdge],
        rel: str,
        symbol_names: dict[str, str],
        class_methods: dict[str, set[str]],
    ) -> None:
        """Recursively find method_invocation and object_creation_expression nodes."""
        for child in node.children:
            if child.type == METHOD_INVOCATION:
                call = self._resolve_method_call(child, rel, symbol_names, class_methods)
                if call:
                    calls.append(call)
            elif child.type == OBJECT_CREATION_EXPRESSION:
                call = self._resolve_constructor_call(child, rel)
                if call:
                    calls.append(call)
            self._walk_for_calls(child, calls, rel, symbol_names, class_methods)

    def _resolve_method_call(
        self,
        node: Any,
        rel: str,
        symbol_names: dict[str, str],
        class_methods: dict[str, set[str]],
    ) -> CallEdge | None:
        """Resolve a method_invocation node.

        Tree-sitter Java AST patterns:
        - simple: method()
          children: [identifier, argument_list]
        - this.method(): this.method()
          children: [this, ., identifier, argument_list]
        - obj.method(): obj.method()
          children: [identifier, ., identifier, argument_list]
        - chained: a.b().c()
          children: [method_invocation, ., identifier, argument_list]
        """
        line = node.start_point[0] + 1
        children = list(node.children)
        if not children:
            return None

        # Find the object (if any) and method name
        object_name = None
        method_name = None

        # Check for 'this' or 'super' as the object
        for child in children:
            if child.type == "this":
                object_name = "this"
            elif child.type == "super":
                object_name = "super"
            elif child.type == IDENTIFIER:
                # Could be object or method name — determine by position
                pass

        # Find identifiers
        identifiers = [(i, c) for i, c in enumerate(children) if c.type == IDENTIFIER]
        # Check if first child is a method_invocation (chained call)
        first_is_call = children[0].type == METHOD_INVOCATION if children else False

        if first_is_call:
            # Chained: a.b().c() — method_name is the identifier after the dot
            for i, child in enumerate(children):
                if child.type == IDENTIFIER and i > 0:
                    method_name = self._text(child)
                    break
        elif object_name is not None:
            # this.method() or super.method()
            # method_name is the identifier
            for child in children:
                if child.type == IDENTIFIER:
                    method_name = self._text(child)
                    break
        elif len(identifiers) >= 2:
            # obj.method() or ClassName.staticMethod()
            idx0 = identifiers[0][0]
            # First identifier before a dot is the object
            has_dot = any(c.type == "." for c in children[idx0:idx0 + 3])
            if has_dot:
                object_name = self._text(identifiers[0][1])
                method_name = self._text(identifiers[1][1])
            else:
                method_name = self._text(identifiers[0][1])
        elif len(identifiers) == 1:
            # Simple method call: method()
            method_name = self._text(identifiers[0][1])

        if method_name is None:
            return None

        if object_name:
            if object_name == "this":
                return CallEdge(
                    source_node_id="",
                    target_expression=f"this.{method_name}",
                    target_qualified_name=f"this.{method_name}",
                    line=line,
                    call_expr=f"this.{method_name}()",
                    is_dynamic=False,
                )
            elif object_name == "super":
                return CallEdge(
                    source_node_id="",
                    target_expression=f"super.{method_name}",
                    target_qualified_name=f"super.{method_name}",
                    line=line,
                    call_expr=f"super.{method_name}()",
                    is_dynamic=False,
                )
            elif object_name[0].isupper():
                # Static method call: ClassName.staticMethod()
                return CallEdge(
                    source_node_id="",
                    target_expression=f"{object_name}.{method_name}",
                    target_qualified_name=f"{object_name}.{method_name}",
                    line=line,
                    call_expr=f"{object_name}.{method_name}()",
                    is_dynamic=False,
                )
            else:
                # Instance method call: obj.method()
                return CallEdge(
                    source_node_id="",
                    target_expression=f"{object_name}.{method_name}",
                    target_qualified_name=f"{object_name}.{method_name}",
                    line=line,
                    call_expr=f"{object_name}.{method_name}()",
                    is_dynamic=True,
                )
        else:
            # Simple method call: methodName()
            return CallEdge(
                source_node_id="",
                target_expression=method_name,
                target_qualified_name=method_name,
                line=line,
                call_expr=f"{method_name}()",
                is_dynamic=False,
            )

    def _resolve_constructor_call(self, node: Any, rel: str) -> CallEdge | None:
        """Resolve a new ClassName() call."""
        line = node.start_point[0] + 1
        # Find the type identifier
        cls_name = self._find_child(node, TYPE_IDENTIFIER)
        if cls_name is None:
            cls_name = self._find_child(node, IDENTIFIER)
        if cls_name is None:
            return None
        name = self._text(cls_name)
        return CallEdge(
            source_node_id="",
            target_expression=name,
            target_qualified_name=name,
            line=line,
            call_expr=f"new {name}()",
            is_dynamic=False,
        )

    # ── Reference extraction ───────────────────────────────────────────

    def _extract_references(
        self, root: Any, symbols: list[GraphNode], rel: str
    ) -> list[RefEdge]:
        """Extract non-call reference edges (extends, implements, annotations)."""
        refs: list[RefEdge] = []
        # References are embedding in the structural edges already
        return refs

    # ── Structural edges ───────────────────────────────────────────────

    def _build_structural_edges(
        self,
        symbols: list[GraphNode],
        rel: str,
        imports: list[ImportInfo],
        package_name: str,
    ) -> list[GraphEdge]:
        """Build contains, defined_in, imports, inherits, implements edges."""
        edges: list[GraphEdge] = []
        file_id = rel
        module_id = f"module:{package_name}" if package_name else f"module:{Path(rel).stem}"

        class_nodes: dict[str, GraphNode] = {}
        class_methods: dict[str, list[GraphNode]] = {}

        for s in symbols:
            if s.type in (NodeType.file, NodeType.module):
                continue
            if s.type in (NodeType.class_, NodeType.controller, NodeType.service, NodeType.component):
                class_nodes[s.name] = s
                class_methods[s.name] = []
            elif s.type == NodeType.method and "class_name" in s.metadata:
                cn = s.metadata["class_name"]
                class_methods.setdefault(cn, []).append(s)

        # contains: file → symbol
        for s in symbols:
            if s.type in (NodeType.file, NodeType.module):
                continue
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
                    reason="symbol defined in file",
                ),
            ))

        # class contains method
        for cls_name, methods in class_methods.items():
            if cls_name in class_nodes:
                cls_id = class_nodes[cls_name].id
                for m in methods:
                    edges.append(GraphEdge(
                        id=_next_edge_id(),
                        type=EdgeType.contains,
                        source=cls_id,
                        target=m.id,
                        confidence=1.0,
                        source_location=EdgeLocation(
                            file_path=rel,
                            line_start=m.location.line_start if m.location else 0,
                            line_end=m.location.line_end if m.location else 0,
                        ),
                        metadata=EdgeMetadata(
                            resolution=Resolution.exact_ast_match,
                            provenance="ast",
                            reason=f"method defined in class {cls_name}",
                        ),
                    ))

        # defined_in: symbol → module
        for s in symbols:
            if s.type in (NodeType.file, NodeType.module):
                continue
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
                    reason="symbol defined in module",
                ),
            ))

        # imports edges
        for imp in imports:
            if not imp.local_name or imp.local_name == "*":
                continue
            target = f"external:{imp.module_path}.{imp.imported_name}"
            edges.append(GraphEdge(
                id=_next_edge_id(),
                type=EdgeType.imports,
                source=file_id,
                target=target,
                confidence=0.50,
                source_location=EdgeLocation(
                    file_path=rel,
                    line_start=imp.line,
                    line_end=imp.line,
                ),
                metadata=EdgeMetadata(
                    resolution=Resolution.external_package,
                    provenance="ast",
                    reason=f"import {imp.local_name} from {imp.module_path}",
                ),
            ))

        # inherits edges (extends)
        for cls_node in class_nodes.values():
            extends_name = cls_node.metadata.get("extends")
            if extends_name:
                target = f"unresolved:{extends_name}"
                edges.append(GraphEdge(
                    id=_next_edge_id(),
                    type=EdgeType.inherits,
                    source=cls_node.id,
                    target=target,
                    confidence=0.85,
                    source_location=EdgeLocation(
                        file_path=rel,
                        line_start=cls_node.location.line_start if cls_node.location else 0,
                        line_end=cls_node.location.line_start if cls_node.location else 0,
                    ),
                    metadata=EdgeMetadata(
                        resolution=Resolution.package_local_exact,
                        provenance="ast",
                        reason=f"class {cls_node.name} extends {extends_name}",
                    ),
                ))

            # implements edges
            impl_list = cls_node.metadata.get("implements", [])
            for iface_name in impl_list:
                target = f"unresolved:{iface_name}"
                edges.append(GraphEdge(
                    id=_next_edge_id(),
                    type=EdgeType.inherits,
                    source=cls_node.id,
                    target=target,
                    confidence=0.85,
                    source_location=EdgeLocation(
                        file_path=rel,
                        line_start=cls_node.location.line_start if cls_node.location else 0,
                        line_end=cls_node.location.line_start if cls_node.location else 0,
                    ),
                    metadata=EdgeMetadata(
                        resolution=Resolution.package_local_exact,
                        provenance="ast",
                        reason=f"class {cls_node.name} implements {iface_name}",
                    ),
                ))

        return edges

    def _calls_to_edges(
        self, calls: list[CallEdge], rel: str
    ) -> list[GraphEdge]:
        """Convert CallEdge structs to GraphEdge objects."""
        edges: list[GraphEdge] = []

        for c in calls:
            expr = c.target_expression

            if expr.startswith("this."):
                method_name = expr[5:]
                edges.append(GraphEdge(
                    id=_next_edge_id(),
                    type=EdgeType.calls,
                    source="",
                    target=f"unresolved:this.{method_name}",
                    confidence=0.90,
                    source_location=EdgeLocation(
                        file_path=rel,
                        line_start=c.line,
                        line_end=c.line,
                    ),
                    metadata=EdgeMetadata(
                        resolution=Resolution.this_method_exact,
                        provenance="ast",
                        call_expr=c.call_expr,
                        reason=f"this.{method_name}() call",
                    ),
                ))
            elif expr.startswith("super."):
                method_name = expr[6:]
                edges.append(GraphEdge(
                    id=_next_edge_id(),
                    type=EdgeType.calls,
                    source="",
                    target=f"unresolved:super.{method_name}",
                    confidence=0.85,
                    source_location=EdgeLocation(
                        file_path=rel,
                        line_start=c.line,
                        line_end=c.line,
                    ),
                    metadata=EdgeMetadata(
                        resolution=Resolution.package_local_exact,
                        provenance="ast",
                        call_expr=c.call_expr,
                        reason=f"super.{method_name}() call",
                    ),
                ))
            elif "." in expr and not expr.startswith("this.") and not expr.startswith("super."):
                # ClassName.method() or obj.method()
                parts = expr.split(".", 1)
                if parts[0] and parts[0][0].isupper():
                    resolution = Resolution.static_method_exact
                    confidence = 0.90
                else:
                    resolution = Resolution.unknown_type_method
                    confidence = 0.30
                edges.append(GraphEdge(
                    id=_next_edge_id(),
                    type=EdgeType.calls,
                    source="",
                    target=f"unresolved:{expr}",
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
                        reason=f"method call: {expr}()",
                    ),
                ))
            else:
                # Simple function call: methodName()
                edges.append(GraphEdge(
                    id=_next_edge_id(),
                    type=EdgeType.calls,
                    source="",
                    target=f"unresolved:{expr}",
                    confidence=0.35,
                    source_location=EdgeLocation(
                        file_path=rel,
                        line_start=c.line,
                        line_end=c.line,
                    ),
                    metadata=EdgeMetadata(
                        resolution=Resolution.name_match_candidate,
                        provenance="ast",
                        call_expr=c.call_expr,
                        reason=f"call to {expr}()",
                    ),
                ))

        return edges

    # ── Diagnostics ─────────────────────────────────────────────────

    def _collect_diagnostics(self, root: Any, rel: str) -> list[Diagnostic]:
        """Collect additional diagnostics."""
        diags: list[Diagnostic] = []
        if root.has_error:
            diags.append(Diagnostic(
                level="warning",
                message="Java parse errors detected — some symbols may be incomplete",
                file_path=rel,
            ))
        return diags

    # ── Tree-sitter helpers ──────────────────────────────────────────

    def _text(self, node: Any) -> str:
        if node is None:
            return ""
        try:
            return node.text.decode("utf-8") if hasattr(node, "text") else ""
        except Exception:
            return ""

    def _find_child(self, node: Any, child_type: str) -> Any | None:
        for child in node.children:
            if child.type == child_type:
                return child
        return None

    def _find_children(self, node: Any, child_type: str) -> list[Any]:
        return [c for c in node.children if c.type == child_type]

    def _find_children_recursive(self, node: Any, child_type: str) -> list[Any]:
        results: list[Any] = []
        for child in node.children:
            if child.type == child_type:
                results.append(child)
            results.extend(self._find_children_recursive(child, child_type))
        return results

    def _get_child_text(self, node: Any, child_type: str) -> str | None:
        child = self._find_child(node, child_type)
        if child is None:
            return None
        return self._text(child)
