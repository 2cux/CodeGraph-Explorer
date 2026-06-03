"""Spring Boot framework extraction helpers.

Detects Spring Boot annotations and produces framework nodes/edges:
- @RestController, @Controller, @Service, @Repository, @Component
- @RequestMapping, @GetMapping, @PostMapping, @PutMapping, @PatchMapping, @DeleteMapping
- Constructor injection / @Autowired DI

Follows the same pattern as TS/JS frameworks.py.
"""

from __future__ import annotations

import hashlib
import re
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


# Spring Boot stereotype annotations
SPRING_STEREOTYPES = {
    "RestController": ("controller", Resolution.spring_rest_controller),
    "Controller": ("controller", Resolution.spring_controller),
    "Service": ("service", Resolution.spring_service),
    "Repository": ("repository", Resolution.spring_repository),
    "Component": ("component", Resolution.spring_component),
}

# Spring Boot route mapping annotations
SPRING_ROUTE_ANNOTATIONS = {
    "RequestMapping": None,  # method not specified
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "PatchMapping": "PATCH",
    "DeleteMapping": "DELETE",
}


@dataclass
class FrameworkExtraction:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


class FrameworkResolver:
    """Base class for Java framework resolvers."""
    framework_id = "generic"

    def extract(
        self,
        *,
        rel: str,
        src: str,
        symbols: list[GraphNode],
        imports: list[ImportInfo],
    ) -> FrameworkExtraction:
        raise NotImplementedError

    def _line_for_offset(self, src: str, offset: int) -> int:
        return src.count("\n", 0, offset) + 1

    def _route_node(
        self,
        rel: str,
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
            language="java",
            language_id="java",
            framework_id=framework_id,
            location=Location(line_start=line, line_end=line),
            tags=["route", framework_id],
            metadata={
                "support_level": "beta",
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


class SpringResolver(FrameworkResolver):
    """Spring Boot framework resolver.

    Detects:
    - @RestController / @Controller → controller stereotype
    - @Service → service stereotype
    - @Repository → repository stereotype
    - @Component → component stereotype
    - @RequestMapping / @GetMapping / @PostMapping / etc. → route nodes
    - Constructor injection / @Autowired → depends_on edges
    """

    framework_id = "spring"

    def extract(
        self,
        *,
        rel: str,
        src: str,
        symbols: list[GraphNode],
        imports: list[ImportInfo],
    ) -> FrameworkExtraction:
        out = FrameworkExtraction()

        # Check if Spring imports are present
        has_spring = any(
            "springframework" in imp.module_path
            for imp in imports
        )
        if not has_spring:
            # Also check for stereotype annotations directly
            has_spring = any(anno in src for anno in SPRING_STEREOTYPES)

        if not has_spring:
            return out

        # Phase 1: Class-level stereotype detection
        class_annotations = self._extract_class_annotations(src, rel)
        for cls_name, annotations, line in class_annotations:
            for anno_name in annotations:
                if anno_name in SPRING_STEREOTYPES:
                    tag, resolution = SPRING_STEREOTYPES[anno_name]
                    node_id = f"{rel}::{cls_name}"

                    # Update existing class node or create new one
                    existing = self._find_symbol(symbols, node_id)
                    if existing:
                        existing.framework_id = self.framework_id
                        existing.metadata["framework_id"] = self.framework_id
                        existing.metadata["framework_signals"] = {
                            "stereotype": anno_name,
                            "type": tag,
                        }
                    else:
                        # Create stereotype node
                        if tag == "controller":
                            ntype = NodeType.controller
                        elif tag == "service":
                            ntype = NodeType.service
                        elif tag == "component":
                            ntype = NodeType.component
                        else:
                            ntype = NodeType.service  # repository

                        node = GraphNode(
                            id=node_id,
                            type=ntype,
                            name=cls_name,
                            qualified_name=node_id,
                            display_name=cls_name,
                            file_path=rel,
                            language="java",
                            language_id="java",
                            framework_id=self.framework_id,
                            location=Location(line_start=line, line_end=line),
                            tags=[tag, self.framework_id],
                            metadata={
                                "support_level": "beta",
                                "framework_id": self.framework_id,
                            },
                        )
                        out.nodes.append(node)

                    # Add confirmed edge for the stereotype
                    out.edges.append(self._edge(
                        EdgeType.references,
                        node_id,
                        f"annotation:org.springframework.stereotype.{anno_name}",
                        rel,
                        line,
                        resolution,
                        None,
                        {
                            "framework_id": self.framework_id,
                            "stereotype": anno_name,
                            "class_name": cls_name,
                        },
                        f"Spring @{anno_name} stereotype on {cls_name}",
                    ))

        # Phase 2: Route mapping detection
        route_mappings: list[dict] = self._extract_route_mappings(src)
        for rm in route_mappings:
            method = rm["method"]
            route_path = rm["path"]
            handler_method = rm["handler"]
            line = rm["line"]
            controller_class = rm["controller"]

            handler_id = f"{rel}::{controller_class}.{handler_method}"
            route_path = self._normalize_path(rm.get("base_path", ""), route_path)

            route = self._route_node(
                rel,
                self.framework_id,
                method,
                route_path,
                line,
                {
                    "source": "spring_annotation",
                    "annotation": rm["annotation"],
                    "controller": controller_class,
                    "method": handler_method,
                },
            )
            out.nodes.append(route)

            # routes_to edge: route → handler method
            out.edges.append(self._edge(
                EdgeType.routes_to,
                route.id,
                handler_id,
                rel,
                line,
                Resolution.spring_route_resolved,
                None,
                {
                    "framework_id": self.framework_id,
                    "route_path": route_path,
                    "http_method": method,
                    "handler": f"{controller_class}.{handler_method}",
                    "controller": controller_class,
                },
                f"Spring @{rm['annotation']} route to {controller_class}.{handler_method}",
            ))

        # Phase 3: Constructor injection / DI detection
        di_edges = self._extract_constructor_injection(src, rel, symbols, out)
        out.edges.extend(di_edges)

        return out

    def _extract_class_annotations(
        self, src: str, rel: str
    ) -> list[tuple[str, list[str], int]]:
        """Find class-level annotations using regex.

        Returns list of (class_name, annotations_list, line).
        """
        results: list[tuple[str, list[str], int]] = []

        # Find individual class/interface-level annotations first
        for m in re.finditer(
            r'(@\w+(?:\([^)]*\))?)\s*\n'
            r'(?:(?:@\w+(?:\([^)]*\))?)\s*\n)*'
            r'(?:public\s+)?(?:abstract\s+)?(?:final\s+)?'
            r'(?:class|interface)\s+(\w+)',
            src,
        ):
            block = m.group(0)
            cls_name = m.group(2)
            line = self._line_for_offset(src, m.start())

            # Extract all annotation names from the block
            annotations: list[str] = []
            for am in re.finditer(r'@(\w+)', block):
                anno_name = am.group(1)
                if anno_name in SPRING_STEREOTYPES or anno_name in SPRING_ROUTE_ANNOTATIONS:
                    annotations.append(anno_name)

            if annotations:
                results.append((cls_name, annotations, line))

        return results

    def _extract_route_mappings(self, src: str) -> list[dict]:
        """Extract route mapping annotations on methods.

        Handles:
        - @GetMapping — marker annotation (no path → "/")
        - @GetMapping("/path") — path specified
        - @PostMapping(value = "/path") — explicit value=
        - @RequestMapping(value = "/path", method = RequestMethod.GET)
        """
        routes: list[dict] = []

        # Find @RequestMapping on classes (base path)
        base_paths: dict[str, str] = {}
        for m in re.finditer(
            r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']',
            src,
        ):
            base_path = m.group(1)
            cls_name = self._find_enclosing_class(src, m.start())
            if cls_name:
                base_paths[cls_name] = base_path

        # Pattern for each route annotation with or without path
        for anno_name, http_method in SPRING_ROUTE_ANNOTATIONS.items():
            if http_method is None:
                # RequestMapping — skip for now, handled differently
                continue

            # Match @Annotation with optional value and following method
            # Pattern 1: @Annotation("/path")\n...methodName()
            pattern_with_path = re.compile(
                r'@' + anno_name + r'\s*\(\s*(?:value\s*=\s*)?["\']([^"\']*)["\'][^)]*\)'
                r'\s*\n\s*'
                r'(?:public\s+|private\s+|protected\s+)?'
                r'(?:static\s+)?'
                r'(?:<[^>]+>\s*)?'
                r'(?:\w+(?:\s*<[^>]+>)?\s+)'
                r'(\w+)\s*\(',
            )

            # Pattern 2: @Annotation\n...methodName()  (marker, no parens)
            pattern_marker = re.compile(
                r'@' + anno_name + r'\s*\n\s*'
                r'(?:public\s+|private\s+|protected\s+)?'
                r'(?:static\s+)?'
                r'(?:<[^>]+>\s*)?'
                r'(?:\w+(?:\s*<[^>]+>)?\s+)'
                r'(\w+)\s*\(',
            )

            for m in pattern_with_path.finditer(src):
                line = self._line_for_offset(src, m.start())
                route_path = m.group(1) or "/"
                handler = m.group(2) if m.lastindex and m.lastindex >= 2 else ""

                if not handler:
                    continue

                cls_name = self._find_enclosing_class(src, m.start())
                if not cls_name:
                    continue

                routes.append({
                    "annotation": anno_name,
                    "method": http_method.upper(),
                    "path": route_path,
                    "handler": handler,
                    "line": line,
                    "controller": cls_name,
                    "base_path": base_paths.get(cls_name, ""),
                })

            # Marker annotations: already handled by pattern_with_path if they have (),
            # but @GetMapping without () is a marker that won't be matched.
            # Check for this pattern explicitly
            for m in pattern_marker.finditer(src):
                line = self._line_for_offset(src, m.start())
                handler = m.group(1)

                # Skip if already captured by pattern_with_path
                already_captured = any(
                    r["handler"] == handler and r["annotation"] == anno_name
                    for r in routes
                )
                if already_captured:
                    continue

                cls_name = self._find_enclosing_class(src, m.start())
                if not cls_name:
                    continue

                routes.append({
                    "annotation": anno_name,
                    "method": http_method.upper(),
                    "path": "/",
                    "handler": handler,
                    "line": line,
                    "controller": cls_name,
                    "base_path": base_paths.get(cls_name, ""),
                })

        return routes

    def _find_enclosing_class(self, src: str, pos: int) -> str | None:
        """Find the class that encloses position *pos* in the source."""
        before = src[:pos]
        # Search backwards for class declaration
        for m in re.finditer(
            r'(?:public\s+|private\s+|protected\s+)?'
            r'(?:abstract\s+|final\s+)?'
            r'class\s+(\w+)',
            before,
        ):
            cls_name = m.group(1)
        # Return the last class found before pos
        matches = list(re.finditer(
            r'(?:public\s+|private\s+|protected\s+)?'
            r'(?:abstract\s+|final\s+)?'
            r'class\s+(\w+)',
            before,
        ))
        if matches:
            return matches[-1].group(1)
        return None

    def _normalize_path(self, base: str, route: str) -> str:
        """Combine base path with route path."""
        base_clean = base.strip("/")
        route_clean = route.strip("/")
        if base_clean and route_clean:
            return "/" + base_clean + "/" + route_clean
        elif base_clean:
            return "/" + base_clean
        elif route_clean:
            return "/" + route_clean
        return "/"

    def _extract_constructor_injection(
        self,
        src: str,
        rel: str,
        symbols: list[GraphNode],
        out: FrameworkExtraction,
    ) -> list[GraphEdge]:
        """Extract constructor injection dependencies.

        Pattern:
            public ClassName(DependencyType depName) { ... }

        Also handles @Autowired on constructors.
        """
        edges: list[GraphEdge] = []

        # Find constructors with parameters (potential injection points)
        class_by_name = self._build_class_map(symbols)

        for cls_name, class_node in class_by_name.items():
            # Find constructor for this class
            pattern = re.compile(
                r'(?:@\w+\s*)*'  # optional annotations
                r'(?:public\s+)?'
                + re.escape(cls_name) + r'\s*\(([^)]*)\)',
                re.DOTALL,
            )
            m = pattern.search(src)
            if not m:
                continue

            params_str = m.group(1)
            if not params_str.strip():
                continue

            line = self._line_for_offset(src, m.start())
            has_autowired = "@Autowired" in src[max(0, m.start() - 50):m.start()]

            # Parse parameters: "Type1 param1, Type2 param2"
            for param in self._split_params(params_str):
                param = param.strip()
                if not param:
                    continue
                # Extract type name (first word before variable name)
                parts = param.split()
                if len(parts) >= 1:
                    type_name = parts[0]
                    # Remove annotations from type
                    type_name = re.sub(r'^@\w+\s+', '', type_name)
                    # Remove generic parameters
                    type_name = re.sub(r'<[^>]+>', '', type_name).strip()

                    if type_name and type_name[0].isupper():
                        resolution = (
                            Resolution.spring_di_constructor
                            if has_autowired
                            else Resolution.spring_bean_candidate
                        )
                        edges.append(self._edge(
                            EdgeType.depends_on,
                            f"{rel}::{cls_name}",
                            f"unresolved:{type_name}",
                            rel,
                            line,
                            resolution,
                            None,
                            {
                                "framework_id": self.framework_id,
                                "dependency": type_name,
                                "injection": "constructor",
                                "has_autowired": has_autowired,
                            },
                            f"Spring constructor injection: {type_name} into {cls_name}",
                        ))

        return edges

    def _split_params(self, params_str: str) -> list[str]:
        """Split constructor parameter string, handling nested generics."""
        params: list[str] = []
        current: list[str] = []
        depth = 0
        for ch in params_str:
            if ch == '<':
                depth += 1
            elif ch == '>':
                depth -= 1
            if ch == ',' and depth == 0:
                params.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        tail = "".join(current).strip()
        if tail:
            params.append(tail)
        return params

    def _build_class_map(
        self, symbols: list[GraphNode]
    ) -> dict[str, GraphNode]:
        """Build a class_name → GraphNode map from symbols."""
        result: dict[str, GraphNode] = {}
        for s in symbols:
            if s.type in (NodeType.class_, NodeType.controller, NodeType.service, NodeType.component):
                if s.name not in result:
                    result[s.name] = s
        return result

    def _find_symbol(self, symbols: list[GraphNode], node_id: str) -> GraphNode | None:
        """Find a symbol by node_id in the list."""
        for s in symbols:
            if s.id == node_id:
                return s
        return None


def extract_spring(
    *,
    rel: str,
    src: str,
    symbols: list[GraphNode],
    imports: list[ImportInfo],
) -> FrameworkExtraction:
    """Main entry point for Spring framework extraction."""
    resolver = SpringResolver()
    return resolver.extract(
        rel=rel,
        src=src,
        symbols=symbols,
        imports=imports,
    )
