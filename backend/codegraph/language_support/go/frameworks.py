"""Go framework-specific extraction helpers.

Detects Gin and Hertz route registrations, router groups, middleware chains,
and builds route nodes with routes_to / references edges.
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GO_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "Any", "Handle"}

# Known stdlib/common names that should NOT be treated as router variables
_ROUTER_VAR_EXCLUDES = {
    "fmt", "os", "io", "net", "http", "sync", "log", "time",
    "strings", "strconv", "context", "errors", "json", "math",
    "bytes", "sort", "path", "filepath", "runtime",
}


# ---------------------------------------------------------------------------
# FrameworkExtraction model
# ---------------------------------------------------------------------------

@dataclass
class FrameworkExtraction:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_quotes(value: str) -> str:
    """Strip surrounding quotes from a string value."""
    value = value.strip()
    if len(value) >= 2:
        if (value[0] == '"' and value[-1] == '"') or \
           (value[0] == "'" and value[-1] == "'") or \
           (value[0] == '`' and value[-1] == '`'):
            return value[1:-1]
    return value


def _join_paths(prefix: str, path: str) -> str:
    """Join a route prefix and path into a single normalized path."""
    left = "/" + prefix.strip("/") if prefix and prefix != "/" else ""
    if path:
        right = "/" + path.strip("/")
    else:
        right = ""
    combined = (left + right) or "/"
    return re.sub(r"/+", "/", combined)


def _split_args(arg_text: str) -> list[str]:
    """Split comma-separated function arguments, respecting nesting and strings."""
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
        if ch in ('"', "'", '`'):
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


def _find_matching_paren(src: str, open_idx: int) -> int | None:
    """Find the matching closing paren for an opening paren at ``open_idx``."""
    depth = 0
    quote: str | None = None
    escape = False
    for i in range(open_idx, len(src)):
        ch = src[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in ('"', "'", "`"):
            quote = ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return None


def _line_for_offset(src: str, offset: int) -> int:
    """Return 1-based line number for character offset."""
    return src[:offset].count("\n") + 1


def _is_inline_handler(expr: str) -> bool:
    """Check if an expression is an inline function literal."""
    expr = expr.strip()
    return expr.startswith("func(") or expr.startswith("func (")


def _resolve_handler_target(
    rel: str,
    expr: str,
    line: int,
    inline_resolution: Resolution,
    route_resolution: Resolution,
) -> tuple[str, Resolution, float]:
    """Determine the handler target for a route registration.

    Shared between Gin and Hertz resolvers. Returns ``(target, resolution, confidence)``.

    Args:
        rel: Relative file path
        expr: The handler expression from the route registration
        line: Line number
        inline_resolution: Resolution enum for inline handlers
        route_resolution: Resolution enum for resolved route handlers
    """
    expr = expr.strip()

    # Inline function literal: func(c *gin.Context) { ... } / func(c context.Context) { ... }
    if _is_inline_handler(expr):
        return (
            f"{rel}::inline_handler:{line}",
            inline_resolution,
            get_confidence(inline_resolution),
        )

    # Simple function name: listUsers
    if re.match(r'^[A-Za-z_]\w*$', expr):
        return (
            f"unresolved:{expr}",
            route_resolution,
            get_confidence(route_resolution),
        )

    # Package-qualified: handlers.CreateUser
    if re.match(r'^[A-Za-z_]\w*\.[A-Za-z_]\w*$', expr):
        return (
            f"unresolved:{expr}",
            route_resolution,
            get_confidence(route_resolution),
        )

    # Anonymous / unrecognized expression
    return (
        f"{rel}::inline_handler:{line}",
        inline_resolution,
        get_confidence(inline_resolution),
    )


# ── Route call detectors (shared across Go frameworks) ────────────────────

_RE_GO_HTTP_METHOD_CALL = re.compile(
    r'(\w+)\.(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|Any|Handle)\s*\(',
)

_RE_GO_GROUP_CALL = re.compile(
    r'(\w+)\.Group\s*\(\s*([^)]*)\)',
)

_RE_GO_USE_CALL = re.compile(
    r'(\w+)\.Use\s*\(',
)

_RE_GO_VAR_ASSIGN = re.compile(
    r'(?:var\s+)?(\w+)\s*:?=\s*',
)

# ── Gin-specific patterns ─────────────────────────────────────────────────

_RE_GIN_ENGINE = re.compile(
    r'gin\.(Default|New)\s*\(',
)

# ── Hertz-specific patterns ────────────────────────────────────────────────

_RE_HERTZ_ENGINE = re.compile(
    r'server\.(Default|New)\s*\(',
)

# Backwards-compatible aliases (used by existing code / tests)
_RE_GIN_METHOD_CALL = _RE_GO_HTTP_METHOD_CALL
_RE_GIN_GROUP_CALL = _RE_GO_GROUP_CALL
_RE_GIN_USE_CALL = _RE_GO_USE_CALL
_RE_GIN_NEW_DEFAULT = _RE_GIN_ENGINE
_RE_VAR_ASSIGN = _RE_GO_VAR_ASSIGN
_GIN_HTTP_METHODS = _GO_HTTP_METHODS


# ---------------------------------------------------------------------------
# FrameworkResolver base
# ---------------------------------------------------------------------------

class _FrameworkResolver:
    """Base class for Go framework resolvers (Gin, Hertz, etc.)."""

    framework_id: str = "generic"

    # ── Subclass overridables ──────────────────────────────────────────

    @property
    def _import_module_paths(self) -> tuple[str, ...]:
        """Module paths that indicate this framework is imported."""
        return ()

    @property
    def _engine_regex(self) -> re.Pattern:
        """Regex for detecting engine creation (e.g. ``gin.Default()``)."""
        return _RE_GIN_ENGINE  # default, overridden by subclasses

    @property
    def _engine_label(self) -> str:
        """Human-readable label for engine diagnostics."""
        return self.framework_id

    @property
    def _inline_handler_resolution(self) -> Resolution:
        """Resolution enum value for inline handlers."""
        return Resolution.hertz_inline_handler  # overridden by subclasses

    @property
    def _route_resolved_resolution(self) -> Resolution:
        """Resolution enum value for resolved route handlers."""
        return Resolution.hertz_route_resolved  # overridden by subclasses

    @property
    def _middleware_resolution(self) -> Resolution:
        """Resolution enum value for middleware references."""
        return Resolution.hertz_middleware_chain  # overridden by subclasses

    # ── Node / Edge builders ────────────────────────────────────────────

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
            support_level="beta",
            metadata={
                "route_path": path,
                "http_method": method.upper(),
                "framework_id": self.framework_id,
                "support_level": "beta",
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
        enriched = {
            **evidence,
            "framework_id": self.framework_id,
            "provenance": "framework_resolver",
            "resolution": resolution.value,
        }
        return GraphEdge(
            id="edge_" + self.framework_id + "_" + hashlib.sha1(
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

    # ── Shared route extraction logic ───────────────────────────────────

    def _extract_routes(
        self,
        *,
        rel: str,
        src: str,
        symbols: list[GraphNode],
        imports: list[ImportInfo],
        language_id: str,
    ) -> FrameworkExtraction:
        """Extract route nodes and edges from source using shared logic.

        Subclasses can override or call this directly from their ``extract()``.
        """
        out = FrameworkExtraction()

        # Find router variable names
        router_vars = self._find_router_vars(src)

        # Emit engine creation diagnostics
        for m in self._engine_regex.finditer(src):
            line = _line_for_offset(src, m.start())
            out.diagnostics.append(Diagnostic(
                level="info",
                message=f"{self._engine_label} engine detected: {m.group(0)}",
                file_path=rel,
                line=line,
            ))

        # Track group prefixes
        group_prefixes: dict[str, str] = {}

        # Detect router groups
        for m in _RE_GO_GROUP_CALL.finditer(src):
            obj = m.group(1)
            prefix_raw = m.group(2).strip() if m.group(2) else ""
            prefix = _strip_quotes(prefix_raw) if prefix_raw else ""
            line = _line_for_offset(src, m.start())

            if obj in router_vars:
                group_var = self._find_group_var(src, m.end(), obj)
                if group_var and prefix:
                    group_prefixes[group_var] = prefix
                    out.diagnostics.append(Diagnostic(
                        level="info",
                        message=f"{self._engine_label} route group: {group_var} -> {prefix}",
                        file_path=rel,
                        line=line,
                    ))

        # Detect route registrations
        for m in _RE_GO_HTTP_METHOD_CALL.finditer(src):
            obj = m.group(1)
            method_raw = m.group(2)
            method = method_raw.upper()

            # Find matching paren
            open_idx = src.find("(", m.end() - 1)
            if open_idx < 0:
                open_idx = m.end()
            close_idx = _find_matching_paren(src, open_idx)
            if close_idx is None:
                continue

            args_text = src[open_idx + 1:close_idx]
            args_all = _split_args(args_text)

            if len(args_all) < 2:
                continue

            # First arg is the route path
            route_path = _strip_quotes(args_all[0])

            # Determine prefix
            prefix = group_prefixes.get(obj, "")
            full_path = _join_paths(prefix, route_path)

            line = _line_for_offset(src, m.start())

            # Handler is the last argument
            handler_expr = args_all[-1].strip()

            # Check for middleware args between path and handler
            middleware_refs: list[str] = []
            for i in range(1, len(args_all) - 1):
                mw = args_all[i].strip()
                if mw and not mw.startswith('"') and not mw.startswith("'"):
                    middleware_refs.append(mw)

            if not handler_expr:
                continue

            # Create route node
            route = self._route_node(
                rel, language_id, method, full_path, line,
                {
                    "source": f"{self.framework_id}_call",
                    "object": obj,
                    "group_prefix": prefix,
                    "has_middleware": bool(middleware_refs),
                },
            )
            out.nodes.append(route)

            # Determine handler target
            target, resolution, confidence = _resolve_handler_target(
                rel, handler_expr, line,
                self._inline_handler_resolution,
                self._route_resolved_resolution,
            )

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
                    "route_path": full_path,
                    "http_method": method,
                    "handler": handler_expr,
                    "object": obj,
                    "group_prefix": prefix,
                    "middleware_count": len(middleware_refs),
                },
                f"{self._engine_label} {method} route declaration",
            ))

            # Add middleware references
            for mw in middleware_refs:
                mw_target = f"unresolved:{mw}"
                out.edges.append(self._edge(
                    EdgeType.references,
                    route.id,
                    mw_target,
                    rel,
                    line,
                    self._middleware_resolution,
                    get_confidence(self._middleware_resolution),
                    {
                        "framework_id": self.framework_id,
                        "middleware": mw,
                        "route_path": full_path,
                    },
                    f"{self._engine_label} middleware reference",
                ))

        return out

    # ── Router variable & group detection ─────────────────────────────

    def _find_router_vars(self, src: str) -> set[str]:
        """Find variable names that hold a framework router/engine."""
        router_vars: set[str] = set()

        # Engine creation assigned to a variable
        for m in self._engine_regex.finditer(src):
            before = src[:m.start()]
            assign_match = list(re.finditer(r'(\w+)\s*:?=\s*$', before))
            if assign_match:
                router_vars.add(assign_match[-1].group(1))

        # Group() calls assigned to a variable
        for m in _RE_GO_GROUP_CALL.finditer(src):
            before = src[:m.start()]
            assign_match = list(re.finditer(r'(\w+)\s*:?=\s*$', before))
            if assign_match:
                router_vars.add(assign_match[-1].group(1))

        # Any variable that has .GET/.POST etc. called on it (exclude known non-routers)
        for m in _RE_GO_HTTP_METHOD_CALL.finditer(src):
            obj = m.group(1)
            if obj not in _ROUTER_VAR_EXCLUDES:
                router_vars.add(obj)

        return router_vars

    def _find_group_var(self, src: str, offset: int, router_var: str) -> str | None:
        """Find the variable name assigned from a router.Group() call."""
        before = src[:offset + 1]
        line_start = before.rfind('\n', 0, offset) + 1
        line_end = src.find('\n', offset)
        line = src[line_start:line_end].strip() if line_end >= 0 else src[line_start:]

        assign_match = re.match(r'(\w+)\s*:?=\s*' + re.escape(router_var), line)
        if assign_match:
            return assign_match.group(1)

        return None


# ---------------------------------------------------------------------------
# GinResolver
# ---------------------------------------------------------------------------

class GinResolver(_FrameworkResolver):
    """Detect Gin route registrations, router groups, and middleware chains."""

    framework_id = "gin"

    @property
    def _import_module_paths(self) -> tuple[str, ...]:
        return ("github.com/gin-gonic/gin",)

    @property
    def _engine_regex(self) -> re.Pattern:
        return _RE_GIN_ENGINE

    @property
    def _engine_label(self) -> str:
        return "Gin"

    @property
    def _inline_handler_resolution(self) -> Resolution:
        return Resolution.gin_inline_handler

    @property
    def _route_resolved_resolution(self) -> Resolution:
        return Resolution.gin_route_resolved

    @property
    def _middleware_resolution(self) -> Resolution:
        return Resolution.gin_middleware_chain

    def extract(
        self,
        *,
        rel: str,
        src: str,
        symbols: list[GraphNode],
        imports: list[ImportInfo],
        language_id: str,
    ) -> FrameworkExtraction:
        # Check if gin is imported
        gin_imported = False
        for imp in imports:
            if imp.module_path in self._import_module_paths:
                gin_imported = True
                break

        if not gin_imported:
            # Also check if gin.Default() or gin.New() is called as heuristic
            if not _RE_GIN_ENGINE.search(src):
                return FrameworkExtraction()

        return self._extract_routes(
            rel=rel,
            src=src,
            symbols=symbols,
            imports=imports,
            language_id=language_id,
        )


# ---------------------------------------------------------------------------
# HertzResolver
# ---------------------------------------------------------------------------

class HertzResolver(_FrameworkResolver):
    """Detect Hertz route registrations, router groups, and middleware chains.

    Compatible imports:
        - ``github.com/cloudwego/hertz/pkg/app/server``
        - ``github.com/cloudwego/hertz/pkg/app``
        - ``github.com/cloudwego/hertz/pkg/protocol/consts``
    """

    framework_id = "hertz"

    _HERTZ_IMPORT_MODULES = (
        "github.com/cloudwego/hertz/pkg/app/server",
        "github.com/cloudwego/hertz/pkg/app",
        "github.com/cloudwego/hertz/pkg/protocol/consts",
    )

    @property
    def _import_module_paths(self) -> tuple[str, ...]:
        return self._HERTZ_IMPORT_MODULES

    @property
    def _engine_regex(self) -> re.Pattern:
        return _RE_HERTZ_ENGINE

    @property
    def _engine_label(self) -> str:
        return "Hertz"

    @property
    def _inline_handler_resolution(self) -> Resolution:
        return Resolution.hertz_inline_handler

    @property
    def _route_resolved_resolution(self) -> Resolution:
        return Resolution.hertz_route_resolved

    @property
    def _middleware_resolution(self) -> Resolution:
        return Resolution.hertz_middleware_chain

    def extract(
        self,
        *,
        rel: str,
        src: str,
        symbols: list[GraphNode],
        imports: list[ImportInfo],
        language_id: str,
    ) -> FrameworkExtraction:
        # Check if Hertz is imported
        hertz_imported = False
        for imp in imports:
            if imp.module_path in self._import_module_paths:
                hertz_imported = True
                break

        if not hertz_imported:
            # Also check if server.Default() or server.New() is called as heuristic
            if not _RE_HERTZ_ENGINE.search(src):
                return FrameworkExtraction()

        return self._extract_routes(
            rel=rel,
            src=src,
            symbols=symbols,
            imports=imports,
            language_id=language_id,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def extract_go_frameworks(
    *,
    rel: str,
    src: str,
    symbols: list[GraphNode],
    imports: list[ImportInfo],
    language_id: str,
) -> FrameworkExtraction:
    """Run all Go framework extractors and merge results."""
    combined = FrameworkExtraction()
    for resolver in (GinResolver(), HertzResolver()):
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
