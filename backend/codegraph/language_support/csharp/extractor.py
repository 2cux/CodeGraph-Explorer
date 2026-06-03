"""C# extractor — regex-based AST extraction.

Extracts namespaces, usings, classes, interfaces, enums, methods,
constructors, properties, fields, constants, method calls, and
attribute metadata from C# source files.

Beta-level: regex-based only, no Roslyn semantic analysis.
"""

from __future__ import annotations

import re
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
from codegraph.graph.confidence import get_confidence
from codegraph.language_support.extractor import (
    LanguageExtractor,
    ExtractorResult,
    ImportInfo,
    ExportInfo,
    CallEdge,
    RefEdge,
    RouteInfo,
    Diagnostic,
)
from codegraph.language_support.csharp.frameworks import extract_frameworks

# ── Regex patterns ──────────────────────────────────────────────────────

# Matches a C# identifier (including generic type params like List<int>)
_ID = r"[A-Za-z_]\w*"
_FULL_ID = r"[A-Za-z_][\w.]*"
_TYPE_NAME = r"[A-Za-z_][\w.<>,\[\] ?]*?"

# Namespace: namespace Foo.Bar { or namespace Foo.Bar;
_RE_NAMESPACE = re.compile(
    r"namespace\s+(" + _FULL_ID + r")\s*[;\{]", re.MULTILINE
)

# Using: using Foo.Bar; / using alias = Foo.Bar.Type; / using static Foo.Bar;
_RE_USING = re.compile(
    r"using\s+(?:static\s+)?(" + _FULL_ID + r")\s*;", re.MULTILINE
)
_RE_USING_ALIAS = re.compile(
    r"using\s+(" + _ID + r")\s*=\s*(" + _FULL_ID + r")\s*;", re.MULTILINE
)

# Class: [attributes] modifiers class Name<T> : BaseClass, IInterface {
_RE_CLASS = re.compile(
    r"(?:\[[\s\S]*?\]\s*)*"  # attributes
    r"(?:(?:public|private|protected|internal|static|sealed|abstract|partial|unsafe)\s+)*"
    r"class\s+(" + _ID + r")(?:<[^>]*>)?"
    r"(?:\s*:\s*([^{]+?))?"  # base class / interfaces
    r"\s*\{",
    re.MULTILINE,
)

# Interface: interface IFoo<T> : IBase {
_RE_INTERFACE = re.compile(
    r"(?:\[[\s\S]*?\]\s*)*"
    r"(?:(?:public|private|protected|internal)\s+)*"
    r"interface\s+(" + _ID + r")(?:<[^>]*>)?"
    r"(?:\s*:\s*([^{]+?))?"
    r"\s*\{",
    re.MULTILINE,
)

# Enum: enum Foo { or [Flags] enum Foo : int {
_RE_ENUM = re.compile(
    r"(?:\[[\s\S]*?\]\s*)*"
    r"(?:(?:public|private|protected|internal)\s+)*"
    r"enum\s+(" + _ID + r")"
    r"(?:\s*:\s*\w+)?"
    r"\s*\{",
    re.MULTILINE,
)

# Record: record Foo(int X, string Y);
_RE_RECORD = re.compile(
    r"(?:\[[\s\S]*?\]\s*)*"
    r"(?:(?:public|private|protected|internal|sealed|readonly)\s+)*"
    r"(?:record\s+(?:class|struct)\s+)?record\s+(" + _ID + r")",
    re.MULTILINE,
)

# Method: [attributes] modifiers ReturnType Name<T>(params) {
# Also matches async, static, virtual, override, abstract
_RE_METHOD = re.compile(
    r"(?:\[[\s\S]*?\]\s*)?"  # attributes
    r"(?:(?:public|private|protected|internal|static|virtual|override|abstract|async|sealed|new|unsafe|partial|extern)\s+)*"
    r"(" + _TYPE_NAME + r")\s+"
    r"(" + _ID + r")(?:<[^>]*>)?\s*"
    r"\(([^)]*)\)",
    re.MULTILINE,
)

# Constructor: [attributes] modifiers ClassName(params) : base(...) / : this(...)
_RE_CONSTRUCTOR = re.compile(
    r"(?:\[[\s\S]*?\]\s*)?"
    r"(?:(?:public|private|protected|internal|static)\s+)*"
    r"(" + _ID + r")\s*"
    r"\(([^)]*)\)"
    r"(?:\s*:\s*(?:base|this)\s*\([^)]*\))?"
    r"\s*\{",
    re.MULTILINE,
)

# Property: modifiers Type Name { get; set; } or => expression
_RE_PROPERTY = re.compile(
    r"(?:\[[\s\S]*?\]\s*)?"
    r"(?:(?:public|private|protected|internal|static|virtual|override|abstract|new|required|readonly)\s+)*"
    r"(" + _TYPE_NAME + r")\s+"
    r"(" + _ID + r")\s*"
    r"\{\s*(?:get|set|init)[;\}]",
    re.MULTILINE,
)

# Expression-bodied property: Type Name => expr;
_RE_EXPR_PROPERTY = re.compile(
    r"(?:\[[\s\S]*?\]\s*)?"
    r"(?:(?:public|private|protected|internal|static|virtual|override|abstract|new)\s+)*"
    r"(" + _TYPE_NAME + r")\s+"
    r"(" + _ID + r")\s*=>\s*[^;]+;",
    re.MULTILINE,
)

# Field: modifiers Type Name = value; or Type Name;
_RE_FIELD = re.compile(
    r"(?:(?:public|private|protected|internal|static|readonly|const|volatile|new)\s+)*"
    r"(?!(?:class|interface|enum|struct|record|namespace|using|return|if|for|while|switch|try|catch|throw|new|var)\b)"
    r"(" + _TYPE_NAME + r")\s+"
    r"(" + _ID + r")\s*"
    r"(?:=\s*[^;]*)?\s*;",
    re.MULTILINE,
)

# Constant: const Type Name = value;
_RE_CONST = re.compile(
    r"const\s+(" + _TYPE_NAME + r")\s+(" + _ID + r")\s*=\s*([^;]*)\s*;", re.MULTILINE
)

# Attribute on class/method: [AttributeName(args)]
_RE_ATTRIBUTE = re.compile(
    r"\[([A-Za-z_]\w*(?:Attribute)?)\s*(?:\(([^)]*)\))?\s*\]", re.MULTILINE
)

# Method call: Identifier(args) — simple calls
_RE_SIMPLE_CALL = re.compile(
    r"(?<!\.)(?<!new\s)(?<!\w)"  # not member access, not new
    r"(" + _ID + r")\s*"
    r"\(",
    re.MULTILINE,
)

# Member call: obj.Method(args) or this.Method() or base.Method()
_RE_MEMBER_CALL = re.compile(
    r"(?:(\w+)\.)?"  # optional object
    r"(" + _ID + r")\s*"
    r"\(",
    re.MULTILINE,
)

# Constructor call: new Type(args) or new Type { ... }
_RE_NEW_CALL = re.compile(
    r"new\s+(" + _FULL_ID + r")\s*[\(\{]", re.MULTILINE
)

# Await call: await expr.Method(args)
_RE_AWAIT = re.compile(
    r"await\s+", re.MULTILINE
)

# Inheritance specifier (from class declaration)
_RE_INHERITANCE = re.compile(
    r"(?::\s*)\s*(" + _FULL_ID + r")", re.MULTILINE
)

# Lambda: (params) => expr or params => expr
_RE_LAMBDA = re.compile(
    r"(?:\([^)]*\)|\w+)\s*=>", re.MULTILINE
)

# Method kwargs: ref/out/in keywords
_RE_REF_KW = re.compile(r"\b(ref|out|in|params)\s+", re.MULTILINE)


def _read_content(file_path: str, content: str | None = None) -> str:
    if content is not None:
        return content
    return Path(file_path).read_text(encoding="utf-8")


def _rel_path(abs_path: str, project_root: str | None) -> str:
    try:
        rel = Path(abs_path).relative_to(project_root) if project_root else Path(abs_path)
    except (ValueError, TypeError):
        rel = Path(abs_path)
    return rel.as_posix()


def _node_id(file_path: str, name: str) -> str:
    return f"{file_path}::{name}"


def _line_for_offset(src: str, offset: int) -> int:
    return src.count("\n", 0, offset) + 1


def _strip_quotes(s: str) -> str:
    return s.strip().strip("'\"`")


# Edge counter
_edge_counter: list[int] = [0]


def _next_edge_id() -> str:
    _edge_counter[0] += 1
    return f"cs_edge_{_edge_counter[0]:06d}"


# ── CSharpExtractor ──────────────────────────────────────────────────────

class CSharpExtractor(LanguageExtractor):
    """C# source file extractor (.cs).

    Beta-level: regex-based extraction. No Roslyn semantic analysis.
    Extracts namespaces, usings, classes, interfaces, enums, methods,
    constructors, properties, fields, constants, method calls, and
    attribute annotations.
    """

    language_id: str = "csharp"

    def extract(
        self,
        file_path: str,
        content: str | None = None,
        project_root: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> ExtractorResult:
        src = _read_content(file_path, content)
        rel = _rel_path(file_path, project_root)

        symbols: list[GraphNode] = []
        diags: list[Diagnostic] = []

        # File node
        symbols.append(GraphNode(
            id=rel,
            type=NodeType.file,
            name=Path(rel).name,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
        ))

        # Detect namespace
        namespace = self._extract_namespace(src, rel)
        if namespace:
            symbols.append(namespace)

        # Detect usings
        imports = self._extract_usings(src, rel, symbols)

        # Detect classes / interfaces / enums
        class_contexts = self._extract_types(src, rel, namespace, symbols, diags)

        # For each class context, extract members
        for ctx in class_contexts:
            self._extract_members(src, ctx, rel, symbols, diags)

        # Detect top-level methods (Program.cs style, not inside a class)
        if not class_contexts:
            self._extract_top_level_methods(src, rel, symbols, diags)

        # Detect method calls
        calls = self._extract_calls(src, rel, symbols)

        # Detect references (non-call usages)
        references: list[RefEdge] = []

        # Framework extraction (ASP.NET Core)
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
        diags.extend(framework.diagnostics)

        # Build structural edges
        structural = self._build_structural_edges(symbols, rel, imports, namespace)

        # Set language_id and support_level on all symbols
        for s in symbols:
            s.language_id = self.language_id
            s.language = self.language_id
            if s.type not in (NodeType.file,):
                s.metadata["support_level"] = "beta"
                s.support_level = "beta"

        result = ExtractorResult(
            language_id=self.language_id,
            file_path=rel,
            symbols=symbols,
            imports=imports,
            exports=[],
            calls=calls,
            references=references,
            diagnostics=diags,
        )
        result._raw_edges = structural + self._calls_to_edges(calls, symbols, rel) + framework.edges
        return result

    # ── Namespace ──────────────────────────────────────────────────────

    def _extract_namespace(self, src: str, rel: str) -> GraphNode | None:
        m = _RE_NAMESPACE.search(src)
        if not m:
            return None
        name = m.group(1)
        line = _line_for_offset(src, m.start())
        return GraphNode(
            id=_node_id(rel, f"namespace:{name}"),
            type=NodeType.module,
            name=name,
            qualified_name=name,
            display_name=f"namespace {name}",
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
            location=Location(line_start=line, line_end=line),
            signature=f"namespace {name}",
            support_level="beta",
            metadata={"kind": "namespace", "support_level": "beta"},
        )

    # ── Usings ─────────────────────────────────────────────────────────

    def _extract_usings(
        self, src: str, rel: str, symbols: list[GraphNode]
    ) -> list[ImportInfo]:
        """Extract using directives as imports."""
        imports: list[ImportInfo] = []

        for m in _RE_USING.finditer(src):
            ns = m.group(1)
            line = _line_for_offset(src, m.start())
            is_alias = _RE_USING_ALIAS.match(m.group(0))
            if is_alias:
                continue  # handled by alias regex separately

            imports.append(ImportInfo(
                local_name=ns.split(".")[-1],  # last segment
                module_path=ns,
                imported_name="*",
                is_external=self._is_external_ns(ns),
                line=line,
            ))

        for m in _RE_USING_ALIAS.finditer(src):
            alias_name = m.group(1)
            target_ns = m.group(2)
            line = _line_for_offset(src, m.start())
            imports.append(ImportInfo(
                local_name=alias_name,
                module_path=target_ns,
                imported_name=target_ns.split(".")[-1],
                is_external=self._is_external_ns(target_ns),
                line=line,
            ))

        return imports

    def _is_external_ns(self, ns: str) -> bool:
        """Heuristic: System.*, Microsoft.*, and third-party namespaces are external."""
        first = ns.split(".")[0] if "." in ns else ns
        return first in {
            "System", "Microsoft", "Newtonsoft", "AutoMapper", "MediatR",
            "FluentValidation", "Serilog", "NLog", "Dapper", "EntityFrameworkCore",
            "Swashbuckle", "Xunit", "NUnit", "Moq", "FluentAssertions",
            "MassTransit", "Hangfire", "Quartz", "Polly", "RestSharp",
        }

    # ── Type declarations ──────────────────────────────────────────────

    def _extract_types(
        self,
        src: str,
        rel: str,
        namespace: GraphNode | None,
        symbols: list[GraphNode],
        diags: list[Diagnostic],
    ) -> list[dict]:
        """Extract class, interface, enum declarations.

        Returns list of class context dicts for member extraction.
        """
        contexts: list[dict] = []

        for m in _RE_CLASS.finditer(src):
            name = m.group(1)
            bases = m.group(2)
            line = _line_for_offset(src, m.start())
            body_start = m.end() - 1  # position of {

            # Detect attributes on this class
            attrs = self._extract_attributes_before(src, m.start())

            # Determine if it's a controller, service, repository
            tags: list[str] = []
            node_type = NodeType.class_
            for attr_name, attr_args in attrs:
                if attr_name in ("ApiController", "Controller"):
                    node_type = NodeType.controller
                    tags.append("controller")
                    tags.append("aspnetcore")
                elif attr_name == "Route":
                    tags.append("route_attr")

            if name.endswith("Controller"):
                if node_type == NodeType.class_:
                    node_type = NodeType.controller
                tags.append("controller")
            elif name.endswith("Service"):
                node_type = NodeType.service
                tags.append("service")
            elif name.endswith("Repository"):
                tags.append("persistence")
            elif "DbContext" in name:
                tags.append("persistence")

            qual_name = f"{namespace.name}.{name}" if namespace else name

            node = GraphNode(
                id=_node_id(rel, name),
                type=node_type,
                name=name,
                qualified_name=qual_name,
                display_name=name,
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(line_start=line, line_end=line),
                signature=f"class {name}" + (f" : {bases.strip()}" if bases else ""),
                tags=tags,
                support_level="beta",
                metadata={
                    "support_level": "beta",
                    "namespace": namespace.name if namespace else "",
                    "base_types": [b.strip() for b in bases.split(",")] if bases else [],
                },
            )
            symbols.append(node)

            # Close brace position for scope
            close_brace = self._find_matching_brace(src, body_start)
            contexts.append({
                "class_name": name,
                "body_start": body_start,
                "body_end": close_brace or len(src),
                "base_text": bases,
                "namespace": namespace.name if namespace else "",
            })

        # Interfaces
        for m in _RE_INTERFACE.finditer(src):
            name = m.group(1)
            bases = m.group(2)
            line = _line_for_offset(src, m.start())
            body_start = m.end() - 1
            qual_name = f"{namespace.name}.{name}" if namespace else name

            node = GraphNode(
                id=_node_id(rel, name),
                type=NodeType.class_,
                name=name,
                qualified_name=qual_name,
                display_name=name,
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(line_start=line, line_end=line),
                signature=f"interface {name}" + (f" : {bases.strip()}" if bases else ""),
                tags=["interface"],
                support_level="beta",
                metadata={
                    "support_level": "beta",
                    "namespace": namespace.name if namespace else "",
                    "csharp_kind": "interface",
                    "base_types": [b.strip() for b in bases.split(",")] if bases else [],
                },
            )
            symbols.append(node)

        # Enums
        for m in _RE_ENUM.finditer(src):
            name = m.group(1)
            line = _line_for_offset(src, m.start())
            body_start = m.end() - 1
            qual_name = f"{namespace.name}.{name}" if namespace else name

            node = GraphNode(
                id=_node_id(rel, name),
                type=NodeType.class_,
                name=name,
                qualified_name=qual_name,
                display_name=name,
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(line_start=line, line_end=line),
                signature=f"enum {name}",
                tags=["enum"],
                support_level="beta",
                metadata={
                    "support_level": "beta",
                    "namespace": namespace.name if namespace else "",
                    "csharp_kind": "enum",
                },
            )
            symbols.append(node)

        return contexts

    # ── Member extraction ──────────────────────────────────────────────

    def _extract_members(
        self,
        src: str,
        ctx: dict,
        rel: str,
        symbols: list[GraphNode],
        diags: list[Diagnostic],
    ) -> None:
        """Extract methods, constructors, properties, fields within a class body."""
        class_name = ctx["class_name"]
        body = src[ctx["body_start"]:ctx["body_end"]]
        body_offset = ctx["body_start"]

        # Methods
        for m in _RE_METHOD.finditer(body):
            return_type = m.group(1).strip()
            method_name = m.group(2).strip()
            params = m.group(3).strip()

            # Skip keywords that look like type names
            if return_type in ("if", "for", "while", "switch", "return", "throw", "new",
                               "using", "lock", "fixed", "checked", "unchecked", "typeof",
                               "sizeof", "nameof", "default", "case", "goto"):
                continue
            # Skip property accessors (get/set)
            if method_name in ("get", "set", "add", "remove"):
                continue

            abs_pos = body_offset + m.start()
            line = _line_for_offset(src, abs_pos)

            # Detect attributes from the matched method text (includes attribute prefix)
            match_text = body[m.start():m.end()]
            attrs: list[tuple[str, str]] = []
            for am in _RE_ATTRIBUTE.finditer(match_text):
                name = am.group(1)
                args = am.group(2) or ""
                if name.endswith("Attribute"):
                    name = name[:-9]
                attrs.append((name, args))

            # Check if constructor
            is_ctor = method_name == class_name
            node_type = NodeType.method

            # Detect http method attributes
            http_method = None
            route_path = None
            for an, aa in attrs:
                if an in ("HttpGet", "HttpPost", "HttpPut", "HttpPatch", "HttpDelete"):
                    http_method = an.replace("Http", "").upper()
                    route_path = _strip_quotes(aa) if aa else ""
                elif an == "Route" and aa:
                    route_path = _strip_quotes(aa)

            qual_name = f"{ctx['namespace']}.{class_name}.{method_name}" if ctx.get("namespace") else f"{class_name}.{method_name}"

            node = GraphNode(
                id=_node_id(rel, f"{class_name}.{method_name}"),
                type=node_type,
                name=method_name,
                qualified_name=qual_name,
                display_name=f"{class_name}.{method_name}",
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(line_start=line, line_end=line),
                signature=f"{'async ' if 'async' in m.group(0) else ''}{return_type} {method_name}({params})",
                tags=(["aspnetcore"] if http_method else []),
                support_level="beta",
                metadata={
                    "support_level": "beta",
                    "class_name": class_name,
                    "return_type": return_type,
                    "parameters": params,
                    "http_method": http_method,
                    "route_path": route_path,
                    "is_constructor": is_ctor,
                    "attributes": [(a, ar) for a, ar in attrs],
                },
            )
            symbols.append(node)

        # Constructors (if separate regex matched, but _RE_METHOD already catches them if named same as class)
        # We do a constructor-specific pass for ctor initializers
        for m in _RE_CONSTRUCTOR.finditer(body):
            name = m.group(1)
            if name != class_name:
                continue
            params = m.group(2).strip()
            abs_pos = body_offset + m.start()
            line = _line_for_offset(src, abs_pos)

            qual_name = f"{ctx['namespace']}.{class_name}" if ctx.get("namespace") else class_name
            node_id = _node_id(rel, f"{class_name}._ctor")
            # Avoid duplicate from method pass
            if any(s.id == node_id for s in symbols):
                continue

            node = GraphNode(
                id=node_id,
                type=NodeType.method,
                name=f"{class_name}(constructor)",
                qualified_name=qual_name,
                display_name=f"{class_name}()",
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(line_start=line, line_end=line),
                signature=f"{class_name}({params})",
                tags=["constructor"],
                support_level="beta",
                metadata={
                    "support_level": "beta",
                    "class_name": class_name,
                    "parameters": params,
                    "is_constructor": True,
                },
            )
            symbols.append(node)

        # Properties
        for m in _RE_PROPERTY.finditer(body):
            prop_type = m.group(1).strip()
            prop_name = m.group(2).strip()
            abs_pos = body_offset + m.start()
            line = _line_for_offset(src, abs_pos)

            qual_name = f"{ctx['namespace']}.{class_name}.{prop_name}" if ctx.get("namespace") else f"{class_name}.{prop_name}"
            node = GraphNode(
                id=_node_id(rel, f"{class_name}.{prop_name}"),
                type=NodeType.function,  # property → function type in graph
                name=prop_name,
                qualified_name=qual_name,
                display_name=f"{class_name}.{prop_name}",
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(line_start=line, line_end=line),
                signature=f"{prop_type} {prop_name} {{ get; set; }}",
                tags=["property"],
                support_level="beta",
                metadata={
                    "support_level": "beta",
                    "class_name": class_name,
                    "csharp_kind": "property",
                    "property_type": prop_type,
                },
            )
            symbols.append(node)

        # Expression-bodied properties
        for m in _RE_EXPR_PROPERTY.finditer(body):
            prop_type = m.group(1).strip()
            prop_name = m.group(2).strip()
            # Skip if already matched as regular property
            prop_id = _node_id(rel, f"{class_name}.{prop_name}")
            if any(s.id == prop_id for s in symbols):
                continue
            abs_pos = body_offset + m.start()
            line = _line_for_offset(src, abs_pos)

            qual_name = f"{ctx['namespace']}.{class_name}.{prop_name}" if ctx.get("namespace") else f"{class_name}.{prop_name}"
            node = GraphNode(
                id=prop_id,
                type=NodeType.function,
                name=prop_name,
                qualified_name=qual_name,
                display_name=f"{class_name}.{prop_name}",
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(line_start=line, line_end=line),
                signature=f"{prop_type} {prop_name} =>",
                tags=["property"],
                support_level="beta",
                metadata={
                    "support_level": "beta",
                    "class_name": class_name,
                    "csharp_kind": "property",
                    "property_type": prop_type,
                },
            )
            symbols.append(node)

        # Fields
        for m in _RE_FIELD.finditer(body):
            field_type = m.group(1).strip()
            field_name = m.group(2).strip()
            # Skip fields that look like method/property patterns
            if field_name in ("get", "set", "value", "add", "remove"):
                continue
            # Skip type keywords used as variable names
            if field_type in ("var", "dynamic", "string", "int", "bool", "void",
                             "if", "for", "while", "switch", "return"):
                fpos = body_offset + m.start()
                fline = _line_for_offset(src, fpos)

                qual_name = f"{ctx['namespace']}.{class_name}.{field_name}" if ctx.get("namespace") else f"{class_name}.{field_name}"
                node = GraphNode(
                    id=_node_id(rel, f"{class_name}.{field_name}"),
                    type=NodeType.function,
                    name=field_name,
                    qualified_name=qual_name,
                    display_name=f"{class_name}.{field_name}",
                    file_path=rel,
                    language_id=self.language_id,
                    language=self.language_id,
                    location=Location(line_start=fline, line_end=fline),
                    signature=f"{field_type} {field_name}",
                    tags=["field"],
                    support_level="beta",
                    metadata={
                        "support_level": "beta",
                        "class_name": class_name,
                        "csharp_kind": "field",
                        "field_type": field_type,
                    },
                )
                symbols.append(node)

    # ── Top-level methods (Program.cs, minimal API) ──────────────────

    def _extract_top_level_methods(
        self,
        src: str,
        rel: str,
        symbols: list[GraphNode],
        diags: list[Diagnostic],
    ) -> None:
        """Extract top-level methods (not inside a class)."""
        # Top-level statements in C# 9+: no explicit Main method
        # We detect any top-level method invocations as entry points

        for m in _RE_METHOD.finditer(src):
            return_type = m.group(1).strip()
            method_name = m.group(2).strip()
            params = m.group(3).strip()

            if return_type in ("if", "for", "while", "switch", "return", "throw",
                               "new", "using", "lock", "var", "dynamic"):
                continue

            line = _line_for_offset(src, m.start())
            qual_name = method_name
            node = GraphNode(
                id=_node_id(rel, method_name),
                type=NodeType.function,
                name=method_name,
                qualified_name=qual_name,
                display_name=method_name,
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(line_start=line, line_end=line),
                signature=f"{return_type} {method_name}({params})",
                support_level="beta",
                metadata={"support_level": "beta"},
            )
            symbols.append(node)

    # ── Call extraction ────────────────────────────────────────────────

    def _extract_calls(
        self, src: str, rel: str, symbols: list[GraphNode]
    ) -> list[CallEdge]:
        """Extract method call edges from the source."""
        calls: list[CallEdge] = []

        # Build symbol lookup
        symbol_names: dict[str, str] = {}
        for s in symbols:
            if s.type != NodeType.file:
                symbol_names[s.name] = s.id
                if "." in s.name:
                    symbol_names[s.name.split(".")[-1]] = s.id

        for m in _RE_MEMBER_CALL.finditer(src):
            obj = m.group(1)
            method_name = m.group(2)
            call_start = m.start()
            line = _line_for_offset(src, call_start)

            # Skip if inside string literals or comments (basic check)
            line_text = src.split("\n")[line - 1] if line <= len(src.split("\n")) else ""
            if line_text.strip().startswith("//"):
                continue

            # Build call expression
            full_call = f"{obj}.{method_name}()" if obj else f"{method_name}()"

            # Detect call type
            if obj == "this":
                calls.append(CallEdge(
                    source_node_id="",
                    target_expression=f"this.{method_name}",
                    target_qualified_name=f"this.{method_name}",
                    line=line,
                    call_expr=full_call,
                    is_dynamic=False,
                ))
            elif obj == "base":
                calls.append(CallEdge(
                    source_node_id="",
                    target_expression=f"base.{method_name}",
                    target_qualified_name=f"base.{method_name}",
                    line=line,
                    call_expr=full_call,
                    is_dynamic=False,
                ))
            elif obj and obj[0].isupper():
                # StaticClass.Method()
                calls.append(CallEdge(
                    source_node_id="",
                    target_expression=f"{obj}.{method_name}",
                    target_qualified_name=f"{obj}.{method_name}",
                    line=line,
                    call_expr=full_call,
                    is_dynamic=False,
                ))
            elif obj:
                # instance.Method()
                calls.append(CallEdge(
                    source_node_id="",
                    target_expression=f"{obj}.{method_name}",
                    target_qualified_name=f"{obj}.{method_name}",
                    line=line,
                    call_expr=full_call,
                    is_dynamic=False,
                ))
            elif method_name in symbol_names:
                # Simple call to known symbol
                calls.append(CallEdge(
                    source_node_id="",
                    target_expression=method_name,
                    target_qualified_name=method_name,
                    line=line,
                    call_expr=full_call,
                    is_dynamic=False,
                ))
            else:
                # Unresolved simple call
                calls.append(CallEdge(
                    source_node_id="",
                    target_expression=method_name,
                    target_qualified_name=method_name,
                    line=line,
                    call_expr=full_call,
                    is_dynamic=False,
                ))

        # Constructor calls (new)
        for m in _RE_NEW_CALL.finditer(src):
            type_name = m.group(1).split("<")[0].strip()  # strip generics
            line = _line_for_offset(src, m.start())
            calls.append(CallEdge(
                source_node_id="",
                target_expression=type_name,
                target_qualified_name=type_name,
                line=line,
                call_expr=f"new {m.group(1)}()",
                is_dynamic=False,
            ))

        return calls

    # ── Attribute extraction ───────────────────────────────────────────

    def _extract_attributes_before(self, src: str, pos: int) -> list[tuple[str, str]]:
        """Extract attribute annotations immediately before a given position."""
        # Look backwards for [...] patterns
        before = src[max(0, pos - 500):pos]
        attrs: list[tuple[str, str]] = []
        for m in _RE_ATTRIBUTE.finditer(before):
            name = m.group(1)
            args = m.group(2) or ""
            # Remove "Attribute" suffix if present
            if name.endswith("Attribute"):
                name = name[:-9]
            attrs.append((name, args))
        return attrs[-10:]  # last 10 attributes

    def _extract_attributes_before_in_text(
        self, text: str, pos: int
    ) -> list[tuple[str, str]]:
        """Same as _extract_attributes_before but on a substring."""
        before = text[max(0, pos - 500):pos]
        attrs: list[tuple[str, str]] = []
        for m in _RE_ATTRIBUTE.finditer(before):
            name = m.group(1)
            args = m.group(2) or ""
            if name.endswith("Attribute"):
                name = name[:-9]
            attrs.append((name, args))
        return attrs[-10:]

    # ── Structural edges ───────────────────────────────────────────────

    def _build_structural_edges(
        self,
        symbols: list[GraphNode],
        rel: str,
        imports: list[ImportInfo],
        namespace: GraphNode | None,
    ) -> list[GraphEdge]:
        edges: list[GraphEdge] = []

        file_id = rel
        class_nodes: dict[str, GraphNode] = {}
        members_by_class: dict[str, list[GraphNode]] = {}

        for s in symbols:
            if s.type in (NodeType.class_, NodeType.controller, NodeType.service):
                class_nodes[s.name] = s
                members_by_class[s.name] = []
            elif s.type in (NodeType.method, NodeType.function) and "class_name" in s.metadata:
                cn = s.metadata["class_name"]
                members_by_class.setdefault(cn, []).append(s)

        # File contains symbols
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
                    reason=f"symbol defined in file",
                ),
            ))

        # Class contains members
        for cn, members in members_by_class.items():
            if cn in class_nodes:
                cls_id = class_nodes[cn].id
                for m in members:
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
                        ),
                    ))

        # Namespace contains classes
        if namespace:
            ns_id = namespace.id
            for cn, cls_node in class_nodes.items():
                edges.append(GraphEdge(
                    id=_next_edge_id(),
                    type=EdgeType.contains,
                    source=ns_id,
                    target=cls_node.id,
                    confidence=1.0,
                    metadata=EdgeMetadata(
                        resolution=Resolution.exact_ast_match,
                        provenance="ast",
                    ),
                ))

        # Imports from usings
        for imp in imports:
            imp_node_id = _node_id(rel, f"import:{imp.local_name}")
            target = f"external:{imp.module_path}" if imp.is_external else f"namespace:{imp.module_path}"

            edges.append(GraphEdge(
                id=_next_edge_id(),
                type=EdgeType.imports,
                source=file_id,
                target=target,
                confidence=0.90 if not imp.is_external else 0.50,
                source_location=EdgeLocation(
                    file_path=rel,
                    line_start=imp.line,
                    line_end=imp.line,
                ),
                metadata=EdgeMetadata(
                    resolution=Resolution.using_namespace_exact if not imp.is_external else Resolution.external_package,
                    provenance="ast",
                    reason=f"using '{imp.module_path}'",
                ),
            ))

        # Inheritance edges
        for s in symbols:
            if s.type not in (NodeType.class_, NodeType.controller, NodeType.service):
                continue
            base_types = s.metadata.get("base_types", [])
            for bt in base_types:
                bt = bt.strip()
                if not bt or bt in ("object", "Object"):
                    continue
                    # All inheritance uses 'inherits' edge type
                # Interface implementation is distinguished in metadata
                edge_type = EdgeType.inherits
                edges.append(GraphEdge(
                    id=_next_edge_id(),
                    type=edge_type,
                    source=s.id,
                    target=f"unresolved:{bt}",
                    confidence=0.85,
                    source_location=EdgeLocation(
                        file_path=rel,
                        line_start=s.location.line_start if s.location else 0,
                        line_end=s.location.line_start if s.location else 0,
                    ),
                    metadata=EdgeMetadata(
                        resolution=Resolution.exact_ast_match,
                        provenance="ast",
                        reason=f"inherits {bt}",
                    ),
                ))

        # Route-to edges for controller methods with http attributes
        for s in symbols:
            if s.type != NodeType.method:
                continue
            http_method = s.metadata.get("http_method")
            route_path = s.metadata.get("route_path")
            if http_method and route_path is not None:
                route_node = GraphNode(
                    id=f"{rel}::route:{http_method}:{route_path or '/'}:{s.location.line_start if s.location else 0}",
                    type=NodeType.route,
                    name=f"{http_method} {route_path or '/'}",
                    qualified_name=f"{rel}::route:{http_method}:{route_path or '/'}",
                    display_name=f"{http_method} {route_path or '/'}",
                    file_path=rel,
                    language_id=self.language_id,
                    language=self.language_id,
                    framework_id="aspnetcore",
                    location=s.location,
                    tags=["route", "aspnetcore"],
                    metadata={
                        "route_path": route_path or "/",
                        "http_method": http_method,
                        "framework_id": "aspnetcore",
                    },
                )
                edges.append(GraphEdge(
                    id=_next_edge_id(),
                    type=EdgeType.routes_to,
                    source=route_node.id,
                    target=s.id,
                    confidence=get_confidence(Resolution.aspnetcore_route_attribute),
                    source_location=EdgeLocation(
                        file_path=rel,
                        line_start=s.location.line_start if s.location else 0,
                        line_end=s.location.line_end if s.location else 0,
                    ),
                    metadata=EdgeMetadata(
                        resolution=Resolution.aspnetcore_route_attribute,
                        provenance="framework_resolver",
                        reason=f"ASP.NET Core route [{http_method}] {route_path or '/'} -> {s.name}",
                        evidence={
                            "framework_id": "aspnetcore",
                            "route_path": route_path or "/",
                            "http_method": http_method,
                            "handler": s.name,
                        },
                    ),
                ))

        return edges

    # ── Calls → edges conversion ───────────────────────────────────────

    def _calls_to_edges(
        self, calls: list[CallEdge], symbols: list[GraphNode], rel: str
    ) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        symbol_by_name = {s.name: s.id for s in symbols if s.type != NodeType.file}
        # Also index by simple name (last part of qualified name)
        simple_map: dict[str, str] = {}
        for s in symbols:
            if s.type != NodeType.file:
                simple = s.name.split(".")[-1]
                if simple not in simple_map:
                    simple_map[simple] = s.id

        for c in calls:
            expr = c.target_expression

            if expr.startswith("this."):
                method_name = expr[5:]
                target_id = simple_map.get(method_name)
                resolution = Resolution.this_method_exact if target_id else Resolution.object_method_unknown
                confidence = 0.90 if target_id else 0.35
            elif expr.startswith("base."):
                method_name = expr[5:]
                target_id = simple_map.get(method_name)
                resolution = Resolution.base_method_exact if target_id else Resolution.object_method_unknown
                confidence = 0.88 if target_id else 0.35
            elif "." in expr:
                # StaticClass.Method() or obj.Method()
                parts = expr.split(".")
                method_name = parts[-1]
                target_id = simple_map.get(method_name)
                # Check if the class name matches a known class
                class_name = parts[0]
                cls_target = symbol_by_name.get(class_name)
                if cls_target and target_id:
                    # Check if this method belongs to that class
                    resolution = Resolution.static_method_exact
                    confidence = 0.90
                elif target_id:
                    resolution = Resolution.name_match_candidate
                    confidence = 0.35
                else:
                    resolution = Resolution.object_method_unknown
                    confidence = 0.30
            else:
                target_id = symbol_by_name.get(expr) or simple_map.get(expr)
                resolution = Resolution.same_file_exact if target_id else Resolution.name_match_candidate
                confidence = 0.95 if target_id else 0.35

            # new Type() constructor calls
            if c.call_expr and c.call_expr.startswith("new "):
                target_id = symbol_by_name.get(expr) or simple_map.get(expr)
                resolution = Resolution.same_file_exact if target_id else Resolution.name_match_candidate
                confidence = 0.85 if target_id else 0.35

            edges.append(GraphEdge(
                id=_next_edge_id(),
                type=EdgeType.calls,
                source="",
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

    def _find_matching_brace(self, src: str, open_brace_pos: int) -> int | None:
        """Find the matching close brace for an open brace at the given position."""
        if open_brace_pos >= len(src) or src[open_brace_pos] != "{":
            return None
        depth = 0
        in_string = False
        in_char = False
        in_comment = False
        escape = False

        i = open_brace_pos
        while i < len(src):
            ch = src[i]
            if escape:
                escape = False
                i += 1
                continue
            if in_string:
                if ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            elif in_char:
                if ch == "\\":
                    escape = True
                elif ch == "'":
                    in_char = False
            elif in_comment:
                if ch == "\n":
                    in_comment = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "'":
                    in_char = True
                elif ch == "/" and i + 1 < len(src) and src[i + 1] == "/":
                    in_comment = True
                    i += 1
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return i
                elif ch == "@" and i + 1 < len(src) and src[i + 1] == '"':
                    # Verbatim string
                    in_string = True
                    i += 1
            i += 1
        return None
