"""ASP.NET Core framework extraction helpers.

Detects controller patterns, minimal API routes, DI injection,
and builds framework-specific edges (routes_to, depends_on).
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


@dataclass
class FrameworkExtraction:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


def _strip_quotes(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().strip("'\"`")


def _join_paths(prefix: str, path: str) -> str:
    left = "/" + prefix.strip("/") if prefix else ""
    right = "/" + path.strip("/") if path else ""
    combined = (left + right) or "/"
    return re.sub(r"/+", "/", combined)


def _line_for_offset(src: str, offset: int) -> int:
    return src.count("\n", 0, offset) + 1


def _controller_name_to_route(name: str) -> str:
    """Convert controller class name to route token: UsersController -> users."""
    if name.endswith("Controller"):
        name = name[:-10]
    # PascalCase to kebab-case/kebab (ASP.NET uses lowercase)
    result = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name).lower()
    return result


# ── Controller route extraction ────────────────────────────────────

_RE_CONTROLLER_ROUTE = re.compile(
    r'\[Route\s*\(\s*"([^"]*)"\s*\)\s*\]', re.MULTILINE
)

_RE_HTTP_METHOD_ATTR = re.compile(
    r'\[(HttpGet|HttpPost|HttpPut|HttpPatch|HttpDelete)\s*(?:\(\s*"([^"]*)"\s*\))?\s*\]',
    re.MULTILINE,
)

_RE_CLASS_DECL = re.compile(
    r'class\s+(\w+)',
    re.MULTILINE,
)

# Method declaration with http attributes
_RE_METHOD_WITH_HTTP = re.compile(
    r'\[(HttpGet|HttpPost|HttpPut|HttpPatch|HttpDelete)\s*(?:\(\s*"([^"]*)"\s*\))?\s*\]'
    r'(?:\s*\[[^\]]*\])*'  # other attributes
    r'\s*(?:(?:public|private|protected|internal|async|static|virtual|override)\s+)*'
    r'(?:Task<[^>]*>|[A-Za-z_][\w.<>,\[\] ]*?)\s+'
    r'(\w+)\s*\(',
    re.MULTILINE,
)

# ── Minimal API extraction ─────────────────────────────────────────

_RE_MAP_METHOD = re.compile(
    r'(?:app|group|api)\.(MapGet|MapPost|MapPut|MapPatch|MapDelete|Map)\s*\(\s*'
    r'"([^"]*)"',
    re.MULTILINE,
)

_RE_MAP_GROUP = re.compile(
    r'(?:var\s+)?(\w+)\s*=\s*(?:app|api)\.MapGroup\s*\(\s*"([^"]*)"\s*\)',
    re.MULTILINE,
)

# Simple handler reference: app.MapGet("/path", HandlerMethod)
_RE_HANDLER_REF = re.compile(
    r'\.(MapGet|MapPost|MapPut|MapPatch|MapDelete|Map)\s*\(\s*"[^"]*"\s*,\s*(\w+)\s*\)',
    re.MULTILINE,
)

# Lambda handler: app.MapGet("/path", () => ...) or app.MapGet("/path", async (ctx) => ...)
_RE_LAMBDA_HANDLER = re.compile(
    r'\.(MapGet|MapPost|MapPut|MapPatch|MapDelete|Map)\s*\(\s*"[^"]*"\s*,\s*'
    r'(?:async\s*)?(?:\([^)]*\)\s*=>|[^(]*\s*=>)',
    re.MULTILINE,
)

# ── DI detection ───────────────────────────────────────────────────

_RE_CONSTRUCTOR_PARAM = re.compile(
    r'public\s+\w+\s*\(([^)]*)\)',
    re.MULTILINE,
)

_RE_CONSTRUCTOR_PARAM_DETAIL = re.compile(
    r'(?:private|protected|public|readonly)?\s*(\w+)\s+(\w+)',
    re.MULTILINE,
)

# Service registration: builder.Services.AddScoped<I, T>() / services.AddSingleton<T>()
_RE_ADD_SERVICE = re.compile(
    r'(?:builder\.)?[Ss]ervices\.(AddScoped|AddTransient|AddSingleton|AddDbContext|AddHttpClient)\s*[<\(]',
    re.MULTILINE,
)

# ── AspNetCoreResolver ─────────────────────────────────────────────


class AspNetCoreResolver:
    """Detects ASP.NET Core framework patterns in C# source files.

    Handles:
    - Controller route attributes
    - Minimal API route registration
    - MapGroup prefix composition
    - Constructor-based DI detection
    """

    framework_id = "aspnetcore"

    def extract(
        self,
        *,
        rel: str,
        src: str,
        symbols: list[GraphNode],
        imports: list[ImportInfo],
        language_id: str,
    ) -> FrameworkExtraction:
        out = FrameworkExtraction()

        # Phase 1: Controller route detection
        self._extract_controller_routes(rel, src, symbols, language_id, out)

        # Phase 2: Minimal API detection
        self._extract_minimal_api_routes(rel, src, symbols, language_id, out)

        # Phase 3: DI detection
        self._extract_di_dependencies(rel, src, symbols, language_id, out)

        return out

    # ── Controller routes ──────────────────────────────────────────

    def _extract_controller_routes(
        self,
        rel: str,
        src: str,
        symbols: list[GraphNode],
        language_id: str,
        out: FrameworkExtraction,
    ) -> None:
        """Extract routes from [ApiController]/[Controller] classes."""
        # Find controller-level route
        controller_route = ""
        route_m = _RE_CONTROLLER_ROUTE.search(src)
        if route_m:
            controller_route = route_m.group(1)

        # Find controller class name
        class_m = _RE_CLASS_DECL.search(src)
        if not class_m:
            return
        class_name = class_m.group(1)

        # Resolve [controller] token
        if "[controller]" in controller_route:
            token = _controller_name_to_route(class_name)
            controller_route = controller_route.replace("[controller]", token)

        # Find methods with HTTP attributes
        for m in _RE_METHOD_WITH_HTTP.finditer(src):
            http_attr = m.group(1)
            attr_path = m.group(2) or ""
            method_name = m.group(3)
            http_method = http_attr.replace("Http", "").upper()
            line = _line_for_offset(src, m.start())

            # Combine controller + method route
            route_path = _join_paths(controller_route, attr_path)

            # Find or create route node
            route_node = self._route_node(
                rel, language_id, http_method, route_path, line,
                {
                    "source": "aspnetcore_attribute",
                    "controller": class_name,
                    "method": method_name,
                },
            )
            out.nodes.append(route_node)

            # Find method symbol
            method_id = self._find_method_symbol(symbols, class_name, method_name)
            if not method_id:
                method_node = GraphNode(
                    id=f"{rel}::{class_name}.{method_name}",
                    type=NodeType.method,
                    name=method_name,
                    qualified_name=f"{rel}::{class_name}.{method_name}",
                    display_name=f"{class_name}.{method_name}",
                    file_path=rel,
                    language=language_id,
                    language_id=language_id,
                    framework_id=self.framework_id,
                    location=Location(line_start=line, line_end=line),
                    tags=["aspnetcore"],
                    metadata={
                        "support_level": "beta",
                        "class_name": class_name,
                        "http_method": http_method,
                        "route_path": route_path,
                    },
                )
                out.nodes.append(method_node)
                method_id = method_node.id

            out.edges.append(self._edge(
                EdgeType.routes_to,
                route_node.id,
                method_id,
                rel,
                line,
                Resolution.aspnetcore_route_attribute,
                get_confidence(Resolution.aspnetcore_route_attribute),
                {
                    "framework_id": self.framework_id,
                    "route_path": route_path,
                    "http_method": http_method,
                    "handler": f"{class_name}.{method_name}",
                    "controller": class_name,
                    "source": "attribute_route",
                },
                f"ASP.NET Core route [{http_method}] {route_path} -> {class_name}.{method_name}",
            ))

    # ── Minimal API routes ─────────────────────────────────────────

    def _extract_minimal_api_routes(
        self,
        rel: str,
        src: str,
        symbols: list[GraphNode],
        language_id: str,
        out: FrameworkExtraction,
    ) -> None:
        """Extract routes from minimal API MapGet/MapPost/etc. calls."""
        # Find MapGroup declarations for prefix
        groups: dict[str, str] = {}
        for m in _RE_MAP_GROUP.finditer(src):
            var_name = m.group(1)
            prefix = m.group(2)
            groups[var_name] = prefix

        # Find handler references (named handlers)
        for m in _RE_HANDLER_REF.finditer(src):
            verb_method = m.group(1)
            handler_name = m.group(2)
            line = _line_for_offset(src, m.start())

            http_method = self._map_verb_to_method(verb_method)
            full_match = m.group(0)
            path_m = re.search(r'"([^"]*)"', full_match)
            route_path = path_m.group(1) if path_m else "/"

            group_var = self._find_group_var(src, m.start())
            if group_var and group_var in groups:
                route_path = _join_paths(groups[group_var], route_path)

            self._add_minimal_api_route(
                rel, language_id, http_method, route_path, line,
                handler_name, False, symbols, out,
            )

        # Find lambda-only handlers (no named reference)
        lambda_re = re.compile(
            r'(?:app|group|api)\.(MapGet|MapPost|MapPut|MapPatch|MapDelete|Map)\s*\(\s*'
            r'"([^"]*)"\s*,\s*'
            r'(?:async\s*)?'
            r'(?:\([^)]*\)|[^,)]+)\s*=>',
            re.MULTILINE,
        )
        for m in lambda_re.finditer(src):
            verb_method = m.group(1)
            route_path = m.group(2)
            line = _line_for_offset(src, m.start())
            http_method = self._map_verb_to_method(verb_method)

            group_var = self._find_group_var(src, m.start())
            if group_var and group_var in groups:
                route_path = _join_paths(groups[group_var], route_path)

            self._add_minimal_api_route(
                rel, language_id, http_method, route_path, line,
                f"lambda:{line}", True, symbols, out,
            )

    def _add_minimal_api_route(
        self,
        rel: str,
        language_id: str,
        http_method: str,
        route_path: str,
        line: int,
        handler_name: str,
        is_lambda: bool,
        symbols: list[GraphNode],
        out: FrameworkExtraction,
    ) -> None:
        route_node = self._route_node(
            rel, language_id, http_method, route_path, line,
            {
                "source": "minimal_api",
                "handler": handler_name,
                "is_lambda": is_lambda,
            },
        )
        out.nodes.append(route_node)

        if is_lambda:
            inline_id = f"{rel}::inline_handler:{line}"
            handler_node = GraphNode(
                id=inline_id,
                type=NodeType.function,
                name=f"inline_handler:{line}",
                qualified_name=inline_id,
                display_name=f"inline handler line {line}",
                file_path=rel,
                language=language_id,
                language_id=language_id,
                framework_id=self.framework_id,
                location=Location(line_start=line, line_end=line),
                tags=["inline_handler", self.framework_id],
                metadata={"support_level": "beta", "framework_id": self.framework_id},
            )
            out.nodes.append(handler_node)

            out.edges.append(self._edge(
                EdgeType.routes_to,
                route_node.id,
                handler_node.id,
                rel,
                line,
                Resolution.aspnetcore_minimal_api,
                get_confidence(Resolution.aspnetcore_minimal_api),
                {
                    "framework_id": self.framework_id,
                    "route_path": route_path,
                    "http_method": http_method,
                    "handler": f"lambda:{line}",
                    "is_lambda": True,
                },
                f"Minimal API lambda [{http_method}] {route_path}",
            ))
        else:
            handler_id = self._find_symbol_by_name(symbols, handler_name)
            target = handler_id or f"unresolved:{handler_name}"
            resolution = Resolution.aspnetcore_minimal_api if handler_id else Resolution.callback_candidate

            out.edges.append(self._edge(
                EdgeType.routes_to,
                route_node.id,
                target,
                rel,
                line,
                resolution,
                get_confidence(resolution),
                {
                    "framework_id": self.framework_id,
                    "route_path": route_path,
                    "http_method": http_method,
                    "handler": handler_name,
                },
                f"Minimal API [{http_method}] {route_path} -> {handler_name}",
            ))

    def _find_group_var(self, src: str, pos: int) -> str | None:
        """Try to find which MapGroup variable is used for this route call."""
        before = src[max(0, pos - 200):pos]
        # Look for groupVar.MapGet pattern
        m = re.search(r'(\w+)\.(?:MapGet|MapPost|MapPut|MapPatch|MapDelete|Map)\s*\(\s*"[^"]*"\s*,', before)
        if m:
            return m.group(1)
        return None

    def _map_verb_to_method(self, verb: str) -> str:
        mapping = {
            "MapGet": "GET",
            "MapPost": "POST",
            "MapPut": "PUT",
            "MapPatch": "PATCH",
            "MapDelete": "DELETE",
            "Map": "ALL",
        }
        return mapping.get(verb, "GET")

    # ── DI dependencies ────────────────────────────────────────────

    def _extract_di_dependencies(
        self,
        rel: str,
        src: str,
        symbols: list[GraphNode],
        language_id: str,
        out: FrameworkExtraction,
    ) -> None:
        """Detect constructor-based DI and service registrations."""
        # Constructor injection
        for m in _RE_CONSTRUCTOR_PARAM.finditer(src):
            params_text = m.group(1)
            line = _line_for_offset(src, m.start())

            # Find the enclosing class
            class_name = self._find_enclosing_class(src, m.start())

            for pm in _RE_CONSTRUCTOR_PARAM_DETAIL.finditer(params_text):
                param_type = pm.group(1)
                param_name = pm.group(2)

                # Skip primitive types
                if param_type in ("string", "int", "bool", "long", "double", "float",
                                  "Guid", "DateTime", "CancellationToken", "ILogger",
                                  "IConfiguration", "IWebHostEnvironment"):
                    continue

                if class_name and param_type:
                    # depends_on edge from controller to injected service
                    controller_id = f"{rel}::{class_name}"

                    # Find service symbol
                    service_id = self._find_symbol_by_name(symbols, param_type)
                    target = service_id or f"unresolved:{param_type}"
                    resolution = Resolution.aspnetcore_di_constructor if service_id else Resolution.unknown_type_method

                    out.edges.append(self._edge(
                        EdgeType.depends_on,
                        controller_id if self._has_symbol(symbols, controller_id) else f"{rel}::{class_name}",
                        target,
                        rel,
                        line,
                        resolution,
                        get_confidence(resolution),
                        {
                            "framework_id": self.framework_id,
                            "dependency": param_type,
                            "injection": "constructor",
                        },
                        f"ASP.NET Core constructor injection: {param_type}",
                    ))

        # Service registration in Program.cs / Startup.cs
        for m in _RE_ADD_SERVICE.finditer(src):
            lifetime = m.group(1)
            line = _line_for_offset(src, m.start())
            # This is a signal that a service is registered but we generally can't
            # resolve the specific interface/implementation at extraction time.
            # Mark as a diagnostic / signal.
            out.diagnostics.append(Diagnostic(
                level="info",
                message=f"Service registration detected: {lifetime}",
                file_path=rel,
                line=line,
            ))

    def _find_enclosing_class(self, src: str, pos: int) -> str | None:
        """Find the class name that encloses a given position."""
        before = src[:pos]
        # Find the last class declaration before this position
        for m in reversed(list(_RE_CLASS_DECL.finditer(before))):
            return m.group(1)
        return None

    # ── Helpers ─────────────────────────────────────────────────────

    def _route_node(
        self,
        rel: str,
        language_id: str,
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
            framework_id=self.framework_id,
            location=Location(line_start=line, line_end=line),
            tags=["route", self.framework_id],
            metadata={
                "route_path": path,
                "http_method": method.upper(),
                "framework_id": self.framework_id,
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
        confidence: float,
        evidence: dict[str, Any],
        reason: str,
    ) -> GraphEdge:
        enriched = {
            **evidence,
            "framework_id": self.framework_id,
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
            confidence=confidence,
            source_location=EdgeLocation(file_path=rel, line_start=line, line_end=line),
            metadata=EdgeMetadata(
                resolution=resolution,
                provenance="framework_resolver",
                reason=reason,
                evidence=enriched,
            ),
        )

    def _find_method_symbol(
        self, symbols: list[GraphNode], class_name: str, method_name: str
    ) -> str | None:
        """Find the node ID for a method in a class."""
        target_id = f"::{class_name}.{method_name}"
        for s in symbols:
            if s.id.endswith(target_id):
                return s.id
            if s.name == method_name and s.metadata.get("class_name") == class_name:
                return s.id
        return None

    def _find_symbol_by_name(
        self, symbols: list[GraphNode], name: str
    ) -> str | None:
        """Find a symbol by name."""
        for s in symbols:
            if s.name == name and s.type not in (NodeType.file,):
                return s.id
        return None

    def _has_symbol(self, symbols: list[GraphNode], node_id: str) -> bool:
        """Check if a symbol exists."""
        for s in symbols:
            if s.id == node_id:
                return True
        return False


def extract_frameworks(
    *,
    rel: str,
    src: str,
    symbols: list[GraphNode],
    imports: list[ImportInfo],
    language_id: str,
) -> FrameworkExtraction:
    """Run ASP.NET Core framework extraction on a C# source file."""
    resolver = AspNetCoreResolver()
    return resolver.extract(
        rel=rel,
        src=src,
        symbols=symbols,
        imports=imports,
        language_id=language_id,
    )
