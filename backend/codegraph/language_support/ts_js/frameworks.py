"""Framework-specific TS/JS extraction helpers.

The extractors in this module produce framework nodes and raw framework
edges only. Cross-file certainty is assigned later by the TS/JS resolver.
"""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codegraph.graph.confidence import get_confidence
from codegraph.graph.models import (
    EdgeLocation,
    EdgeMetadata,
    EdgeType,
    GraphEdge,
    GraphNode,
    Location,
    NodeType,
    Resolution,
)
from codegraph.language_support.extractor import Diagnostic, ImportInfo


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
NEST_METHODS = {"Get": "GET", "Post": "POST", "Put": "PUT", "Patch": "PATCH", "Delete": "DELETE"}


@dataclass
class FrameworkExtraction:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


class FrameworkResolver:
    framework_id = "generic"

    def extract(
        self,
        *,
        rel: str,
        src: str,
        symbols: list[GraphNode],
        imports: list[ImportInfo],
        language_id: str,
    ) -> FrameworkExtraction:
        raise NotImplementedError

    def _line_for_offset(self, src: str, offset: int) -> int:
        return src.count("\n", 0, offset) + 1

    def _line_for_text(self, src: str, text: str, start: int = 0) -> int:
        idx = src.find(text, start)
        return self._line_for_offset(src, idx if idx >= 0 else start)

    def _route_node(
        self,
        rel: str,
        language_id: str,
        framework_id: str,
        method: str,
        path: str,
        line: int,
        evidence: dict[str, Any],
    ) -> GraphNode:
        safe_path = path.strip("/") or "root"
        safe_path = re.sub(r"[^A-Za-z0-9_.:-]+", "_", safe_path)
        node_id = f"{rel}::route:{method.upper()}:{safe_path}:{line}"
        return GraphNode(
            id=node_id,
            type=NodeType.route,
            name=f"{method.upper()} {path}",
            qualified_name=node_id,
            display_name=f"{method.upper()} {path}",
            file_path=rel,
            language=language_id,
            language_id=language_id,
            framework_id=framework_id,
            location=Location(line_start=line, line_end=line),
            tags=["route", framework_id],
            metadata={
                "route_path": path,
                "http_method": method.upper(),
                "framework_id": framework_id,
                "framework_signals": evidence,
            },
        )

    def _edge(
        self,
        edge_type: EdgeType,
        source: str,
        target: str,
        rel: str,
        line: int,
        resolution: Resolution,
        confidence: float | None,
        evidence: dict[str, Any],
        reason: str,
    ) -> GraphEdge:
        framework_id = evidence.get("framework_id", self.framework_id)
        enriched = {
            **evidence,
            "framework_id": framework_id,
            "provenance": "framework_resolver",
            "resolution": resolution.value,
        }
        return GraphEdge(
            id="edge_fw_" + hashlib.sha1(
                f"{source}|{target}|{edge_type.value}|{line}|{reason}".encode("utf-8")
            ).hexdigest()[:12],
            type=edge_type,
            source=source,
            target=target,
            confidence=confidence if confidence is not None else get_confidence(resolution),
            source_location=EdgeLocation(file_path=rel, line_start=line, line_end=line),
            metadata=EdgeMetadata(
                resolution=resolution,
                provenance="framework_resolver",
                reason=reason,
                evidence=enriched,
            ),
        )


def _strip_quotes(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().strip("'\"`")


def _join_paths(prefix: str, path: str) -> str:
    left = "/" + prefix.strip("/") if prefix else ""
    right = "/" + path.strip("/") if path else ""
    combined = (left + right) or "/"
    return re.sub(r"/+", "/", combined)


def _split_top_level_args(arg_text: str) -> list[str]:
    args: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    escape = False
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    for ch in arg_text:
        if quote:
            current.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            current.append(ch)
            continue
        if ch in pairs:
            depth += 1
        elif ch in closing and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args


def _symbol_by_name(symbols: list[GraphNode]) -> dict[str, GraphNode]:
    return {s.name: s for s in symbols if s.type not in (NodeType.file, NodeType.module)}


def _symbol_by_id(symbols: list[GraphNode]) -> dict[str, GraphNode]:
    return {s.id: s for s in symbols}


class ExpressResolver(FrameworkResolver):
    framework_id = "express"

    def extract(self, *, rel: str, src: str, symbols: list[GraphNode], imports: list[ImportInfo], language_id: str) -> FrameworkExtraction:
        out = FrameworkExtraction()
        router_vars = {"router"}
        for m in re.finditer(r"\b(?:const|let|var)\s+(\w+)\s*=\s*(?:express\.)?Router\s*\(", src):
            router_vars.add(m.group(1))

        prefixes: dict[str, str] = {}
        for m in re.finditer(r"\b(\w+)\.use\s*\(\s*(['\"`][^'\"`]+['\"`])\s*,\s*(\w+)\s*\)", src):
            prefixes[m.group(3)] = _strip_quotes(m.group(2))

        for obj, method_raw, args_text, start in self._iter_route_calls(src):
            method = method_raw.upper()
            args_all = _split_top_level_args(args_text)
            if len(args_all) < 2:
                continue
            route_path = _join_paths(prefixes.get(obj, ""), _strip_quotes(args_all[0]))
            line = self._line_for_offset(src, start)
            args = args_all[1:]
            handler_expr = args[-1].strip() if args else ""
            if not handler_expr:
                continue
            route = self._route_node(
                rel, language_id, self.framework_id, method, route_path, line,
                {"source": "express_call", "object": obj, "router_prefix": prefixes.get(obj, "")},
            )
            out.nodes.append(route)
            target, resolution, confidence = self._handler_target(rel, handler_expr, line)
            out.nodes.extend(self._inline_node(rel, language_id, line, handler_expr))
            out.edges.append(self._edge(
                EdgeType.routes_to,
                route.id,
                target,
                rel,
                line,
                resolution,
                confidence,
                {
                    "framework_id": self.framework_id,
                    "route_path": route_path,
                    "http_method": method,
                    "handler": handler_expr,
                    "object": obj,
                    "router_prefix": prefixes.get(obj),
                },
                "Express route declaration",
            ))
        return out

    def _iter_route_calls(self, src: str) -> list[tuple[str, str, str, int]]:
        calls: list[tuple[str, str, str, int]] = []
        start_re = re.compile(r"\b(\w+)\.(get|post|put|patch|delete)\s*\(")
        for m in start_re.finditer(src):
            open_idx = src.find("(", m.start())
            if open_idx < 0:
                continue
            close_idx = self._find_matching_paren(src, open_idx)
            if close_idx is None:
                continue
            calls.append((m.group(1), m.group(2), src[open_idx + 1:close_idx], m.start()))
        return calls

    def _find_matching_paren(self, src: str, open_idx: int) -> int | None:
        depth = 0
        quote: str | None = None
        escape = False
        for idx in range(open_idx, len(src)):
            ch = src[idx]
            if quote:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote:
                    quote = None
                continue
            if ch in ("'", '"', "`"):
                quote = ch
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return idx
        return None

    def _handler_target(self, rel: str, expr: str, line: int) -> tuple[str, Resolution, float]:
        if re.match(r"^(async\s*)?(\([^)]*\)|\w+)\s*=>", expr) or expr.startswith("function"):
            return f"{rel}::inline_handler:{line}", Resolution.inline_handler, get_confidence(Resolution.inline_handler)
        if re.match(r"^[A-Za-z_$][\w$]*$", expr):
            return f"unresolved:{expr}", Resolution.express_route_handler, get_confidence(Resolution.express_route_handler)
        if re.match(r"^[A-Za-z_$][\w$]*\.[A-Za-z_$][\w$]*$", expr):
            return f"unresolved:{expr}", Resolution.object_method_unknown, get_confidence(Resolution.object_method_unknown)
        return f"unresolved:{expr}", Resolution.callback_candidate, get_confidence(Resolution.callback_candidate)

    def _inline_node(self, rel: str, language_id: str, line: int, expr: str) -> list[GraphNode]:
        if "=>" not in expr and not expr.startswith("function"):
            return []
        node_id = f"{rel}::inline_handler:{line}"
        return [GraphNode(
            id=node_id,
            type=NodeType.function,
            name=f"inline_handler:{line}",
            qualified_name=node_id,
            display_name=f"inline handler line {line}",
            file_path=rel,
            language=language_id,
            language_id=language_id,
            framework_id=self.framework_id,
            location=Location(line_start=line, line_end=line),
            tags=["inline_handler", self.framework_id],
            support_level="beta",
            metadata={"support_level": "beta", "framework_id": self.framework_id},
        )]


class NextJsResolver(FrameworkResolver):
    framework_id = "nextjs"

    def extract(self, *, rel: str, src: str, symbols: list[GraphNode], imports: list[ImportInfo], language_id: str) -> FrameworkExtraction:
        route_path = self._route_path(rel)
        if route_path is None:
            return FrameworkExtraction()
        out = FrameworkExtraction()
        for method, handler_name, line in self._handlers(rel, src, symbols):
            route = self._route_node(
                rel, language_id, self.framework_id, method, route_path, line,
                {"source": "file_based_route", "file_path": rel},
            )
            out.nodes.append(route)
            out.edges.append(self._edge(
                EdgeType.routes_to,
                route.id,
                f"{rel}::{handler_name}",
                rel,
                line,
                Resolution.nextjs_file_route,
                get_confidence(Resolution.nextjs_file_route),
                {
                    "framework_id": self.framework_id,
                    "route_path": route_path,
                    "http_method": method,
                    "handler": handler_name,
                    "file_based_route": True,
                },
                "Next.js file route handler",
            ))
        return out

    def _route_path(self, rel: str) -> str | None:
        path = rel.replace("\\", "/")
        if path.startswith("pages/api/"):
            body = re.sub(r"\.(tsx?|jsx?|mjs|cjs)$", "", path[len("pages/api/"):])
            return "/api/" + self._normalize_segments(body)
        marker = "/app/api/"
        if path.startswith("app/api/"):
            body = path[len("app/api/"):]
        elif marker in path:
            body = path.split(marker, 1)[1]
        else:
            return None
        if not re.search(r"/?route\.(tsx?|jsx?|mjs|cjs)$", body):
            return None
        body = re.sub(r"/?route\.(tsx?|jsx?|mjs|cjs)$", "", body)
        return "/api/" + self._normalize_segments(body)

    def _normalize_segments(self, body: str) -> str:
        parts = [p for p in body.split("/") if p and p != "index"]
        normalized = [":" + p[1:-1] if p.startswith("[") and p.endswith("]") else p for p in parts]
        return "/".join(normalized).strip("/") or ""

    def _handlers(self, rel: str, src: str, symbols: list[GraphNode]) -> list[tuple[str, str, int]]:
        handlers: list[tuple[str, str, int]] = []
        if rel.replace("\\", "/").startswith("pages/api/"):
            m = re.search(r"export\s+default\s+(?:async\s+)?function\s+(\w+)", src)
            if m:
                handlers.append(("ALL", m.group(1), self._line_for_offset(src, m.start())))
            else:
                m = re.search(r"export\s+default\s+(\w+)", src)
                if m:
                    handlers.append(("ALL", m.group(1), self._line_for_offset(src, m.start())))
            return handlers
        for m in re.finditer(r"export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE)\s*\(", src):
            handlers.append((m.group(1), m.group(1), self._line_for_offset(src, m.start())))
        for m in re.finditer(r"export\s+const\s+(GET|POST|PUT|PATCH|DELETE)\s*=", src):
            handlers.append((m.group(1), m.group(1), self._line_for_offset(src, m.start())))
        return handlers


class NestJsResolver(FrameworkResolver):
    framework_id = "nestjs"

    def extract(self, *, rel: str, src: str, symbols: list[GraphNode], imports: list[ImportInfo], language_id: str) -> FrameworkExtraction:
        out = FrameworkExtraction()
        by_name = _symbol_by_name(symbols)

        for m in re.finditer(r"@Injectable\s*\([^)]*\)\s*(?:export\s+)?class\s+(\w+)", src):
            node = by_name.get(m.group(1))
            if node is None:
                node = GraphNode(
                    id=f"{rel}::{m.group(1)}",
                    type=NodeType.service,
                    name=m.group(1),
                    qualified_name=f"{rel}::{m.group(1)}",
                    display_name=m.group(1),
                    file_path=rel,
                    language=language_id,
                    language_id=language_id,
                    framework_id=self.framework_id,
                    location=Location(line_start=self._line_for_offset(src, m.start()), line_end=self._line_for_offset(src, m.start())),
                    tags=["service", self.framework_id],
                    support_level="beta",
                    metadata={"support_level": "beta"},
                )
                out.nodes.append(node)
                by_name[node.name] = node
            node.type = NodeType.service
            node.framework_id = self.framework_id
            if "service" not in node.tags:
                node.tags.extend(["service", self.framework_id])

        for m in re.finditer(r"@Module\s*\((?P<meta>\{.*?\})\s*\)\s*(?:export\s+)?class\s+(\w+)", src, re.DOTALL):
            node = by_name.get(m.group(2))
            if node is None:
                node = GraphNode(
                    id=f"{rel}::{m.group(2)}",
                    type=NodeType.module,
                    name=m.group(2),
                    qualified_name=f"{rel}::{m.group(2)}",
                    display_name=m.group(2),
                    file_path=rel,
                    language=language_id,
                    language_id=language_id,
                    framework_id=self.framework_id,
                    location=Location(line_start=self._line_for_offset(src, m.start()), line_end=self._line_for_offset(src, m.start())),
                    tags=["module_metadata", self.framework_id],
                    support_level="beta",
                    metadata={"support_level": "beta"},
                )
                out.nodes.append(node)
                by_name[node.name] = node
            node.framework_id = self.framework_id
            node.tags = sorted(set(node.tags + ["module_metadata", self.framework_id]))
            node.metadata["framework_signals"] = {"module_metadata": m.group("meta")[:500]}

        class_re = re.compile(
            r"@Controller\s*\(\s*(?P<base>[^)]*)\)\s*(?:export\s+)?class\s+(?P<name>\w+)[^{]*\{(?P<body>.*?)\n\}",
            re.DOTALL,
        )
        for cls in class_re.finditer(src):
            cls_name = cls.group("name")
            base = _strip_quotes(cls.group("base").strip())
            line = self._line_for_offset(src, cls.start())
            node = by_name.get(cls_name)
            if node is None:
                node = GraphNode(
                    id=f"{rel}::{cls_name}",
                    type=NodeType.controller,
                    name=cls_name,
                    qualified_name=f"{rel}::{cls_name}",
                    display_name=cls_name,
                    file_path=rel,
                    language=language_id,
                    language_id=language_id,
                    framework_id=self.framework_id,
                    location=Location(line_start=line, line_end=line),
                    tags=["controller", self.framework_id],
                    support_level="beta",
                    metadata={"support_level": "beta"},
                )
                out.nodes.append(node)
                by_name[node.name] = node
            node.type = NodeType.controller
            node.framework_id = self.framework_id
            node.tags = sorted(set(node.tags + ["controller", self.framework_id]))
            node.metadata["route_path"] = "/" + base.strip("/") if base else "/"
            body = cls.group("body")
            body_offset = cls.start("body")
            for dep_edge in self._constructor_edges(rel, src, cls_name, body, body_offset):
                out.edges.append(dep_edge)
            for dec in re.finditer(
                r"@(Get|Post|Put|Patch|Delete)\s*\(\s*([^)]*)\)\s*(?:public\s+|private\s+|protected\s+|async\s+)*(\w+)\s*\(",
                body,
            ):
                method = NEST_METHODS[dec.group(1)]
                route_path = _join_paths(base, _strip_quotes(dec.group(2).strip()))
                route_line = self._line_for_offset(src, body_offset + dec.start())
                method_name = dec.group(3)
                method_id = f"{rel}::{cls_name}.{method_name}"
                if method_id not in _symbol_by_id(symbols):
                    out.nodes.append(GraphNode(
                        id=method_id,
                        type=NodeType.method,
                        name=method_name,
                        qualified_name=method_id,
                        display_name=f"{cls_name}.{method_name}",
                        file_path=rel,
                        language=language_id,
                        language_id=language_id,
                        framework_id=self.framework_id,
                        location=Location(line_start=route_line, line_end=route_line),
                        tags=[self.framework_id],
                        support_level="beta",
                        metadata={"class_name": cls_name, "support_level": "beta"},
                    ))
                route = self._route_node(
                    rel, language_id, self.framework_id, method, route_path, route_line,
                    {"source": "nestjs_decorator", "controller": cls_name},
                )
                out.nodes.append(route)
                out.edges.append(self._edge(
                    EdgeType.routes_to,
                    route.id,
                    method_id,
                    rel,
                    route_line,
                    Resolution.nestjs_controller_route,
                    get_confidence(Resolution.nestjs_controller_route),
                    {
                        "framework_id": self.framework_id,
                        "route_path": route_path,
                        "http_method": method,
                        "handler": f"{cls_name}.{method_name}",
                        "controller": cls_name,
                    },
                    "NestJS controller method route",
                ))
        return out

    def _constructor_edges(self, rel: str, src: str, cls_name: str, body: str, body_offset: int) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        m = re.search(r"constructor\s*\((?P<params>.*?)\)", body, re.DOTALL)
        if not m:
            return edges
        params = _split_top_level_args(m.group("params"))
        line = self._line_for_offset(src, body_offset + m.start())
        for param in params:
            type_match = re.search(r":\s*([A-Z]\w*)", param)
            if not type_match:
                continue
            service_name = type_match.group(1)
            edges.append(self._edge(
                EdgeType.depends_on,
                f"{rel}::{cls_name}",
                f"unresolved:{service_name}",
                rel,
                line,
                Resolution.nestjs_injection_resolved,
                get_confidence(Resolution.nestjs_injection_resolved),
                {
                    "framework_id": self.framework_id,
                    "dependency": service_name,
                    "injection": "constructor",
                },
                "NestJS constructor injection",
            ))
        return edges


class ReactResolver(FrameworkResolver):
    framework_id = "react"

    def extract(self, *, rel: str, src: str, symbols: list[GraphNode], imports: list[ImportInfo], language_id: str) -> FrameworkExtraction:
        if not rel.endswith((".tsx", ".jsx")) and "react" not in {i.module_path for i in imports} and "<" not in src:
            return FrameworkExtraction()
        out = FrameworkExtraction()
        component_symbols = self._mark_components(src, symbols)
        for parent in component_symbols:
            if not parent.location:
                continue
            snippet = self._source_for_symbol(src, parent)
            seen: set[str] = set()
            for jsx in re.finditer(r"<([A-Z][A-Za-z0-9_]*)\b", snippet):
                child = jsx.group(1)
                if child == parent.name or child in seen:
                    continue
                seen.add(child)
                line = parent.location.line_start + snippet[:jsx.start()].count("\n")
                out.edges.append(self._edge(
                    EdgeType.references,
                    parent.id,
                    f"unresolved:{child}",
                    rel,
                    line,
                    Resolution.jsx_component_resolved,
                    get_confidence(Resolution.jsx_component_resolved),
                    {
                        "framework_id": self.framework_id,
                        "parent_component": parent.name,
                        "child_component": child,
                    },
                    "JSX component usage",
                ))
        return out

    def _mark_components(self, src: str, symbols: list[GraphNode]) -> list[GraphNode]:
        components: list[GraphNode] = []
        for node in symbols:
            if node.type not in (NodeType.function, NodeType.class_):
                continue
            if not re.match(r"^[A-Z][A-Za-z0-9_]*$", node.name):
                continue
            if node.type == NodeType.class_ and "Component" not in (node.signature or "") and "extends" not in src:
                continue
            node.type = NodeType.component
            node.framework_id = self.framework_id
            node.tags = sorted(set(node.tags + ["component", self.framework_id]))
            node.metadata["framework_id"] = self.framework_id
            if re.search(rf"export\s+default\s+(?:function\s+)?{re.escape(node.name)}\b", src):
                node.metadata["export_default"] = True
            components.append(node)
        return components

    def _source_for_symbol(self, src: str, node: GraphNode) -> str:
        if not node.location:
            return ""
        lines = src.splitlines()
        start = max(node.location.line_start - 1, 0)
        end = min(node.location.line_end, len(lines))
        return "\n".join(lines[start:end])


def extract_frameworks(
    *,
    rel: str,
    src: str,
    symbols: list[GraphNode],
    imports: list[ImportInfo],
    language_id: str,
) -> FrameworkExtraction:
    combined = FrameworkExtraction()
    for resolver in (ExpressResolver(), NextJsResolver(), NestJsResolver(), ReactResolver()):
        result = resolver.extract(
            rel=rel,
            src=src,
            symbols=symbols,
            imports=imports,
            language_id=language_id,
        )
        combined.nodes.extend(result.nodes)
        combined.edges.extend(result.edges)
        combined.diagnostics.extend(result.diagnostics)
    return combined
