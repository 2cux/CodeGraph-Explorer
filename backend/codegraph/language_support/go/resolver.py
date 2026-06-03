"""Go cross-file Resolver.

Resolves import paths, classifies calls into confirmed / possible /
unresolved tiers, and resolves Gin route references.

Implements the ``Resolver`` interface defined in
``codegraph.language_support.resolver``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codegraph.graph.models import (
    GraphNode,
    GraphEdge,
    EdgeType,
    Resolution,
    EdgeMetadata,
    NodeType,
)
from codegraph.graph.impact import (
    is_confirmed_resolution,
    is_possible_resolution,
    is_unresolved_resolution,
)
from codegraph.language_support.resolver import (
    Resolver,
    ResolvedEdge,
    ResolvedEdges,
    GraphContext,
    Provenance,
)
from codegraph.language_support.extractor import ExtractorResult, ImportInfo, CallEdge

# ---------------------------------------------------------------------------
# GoResolver
# ---------------------------------------------------------------------------


class GoResolver(Resolver):
    """Go cross-file edge resolver.

    Resolution strategies:
    - same_package_exact: same-package function calls (0.95)
    - package_import_exact: imported package function calls (0.90)
    - package_function_exact: pkg.Func() pattern matching known imports (0.90)
    - receiver_method_exact: method calls on known receiver types (0.92)
    - local_function_exact: same-file function calls (0.95)

    Rules:
    - name-only matches do NOT enter confirmed
    - functions with same name in different packages are not conflated
    - interface method calls are not directly confirmed
    - unknown receiver types go to possible/unresolved
    - external modules are separately tagged
    """

    language_id = "go"

    def resolve(
        self,
        extractor_results: list[Any],
        graph_context: GraphContext | None = None,
        import_index: dict[str, Any] | None = None,
    ) -> ResolvedEdges:
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved: list[ResolvedEdge] = []

        # Gather all symbols and edges from extractor results
        all_symbols: list[GraphNode] = []
        all_raw_edges: list[GraphEdge] = []
        file_list: list[str] = []
        imports_by_file: dict[str, list[ImportInfo]] = {}
        package_by_file: dict[str, str] = {}

        for er in extractor_results:
            r: ExtractorResult = er
            all_symbols.extend(r.symbols)
            raw = getattr(r, "_raw_edges", [])
            all_raw_edges.extend(raw)
            file_list.append(r.file_path)
            imports_by_file[r.file_path] = r.imports

            # Determine package for each file
            for s in r.symbols:
                if s.type == NodeType.module and s.metadata.get("go_package"):
                    package_by_file[r.file_path] = s.metadata["go_package"]
                    break

        # Build GraphContext if not provided
        ctx = graph_context or self._build_context(all_symbols, file_list, package_by_file)

        # Phase 1: Resolve import edges
        resolved_imports = self._resolve_imports(
            all_raw_edges, imports_by_file, ctx, file_list,
        )
        confirmed.extend(resolved_imports)

        # Phase 2: Resolve call edges
        call_confirmed, call_possible, call_unresolved = self._resolve_calls(
            all_raw_edges, ctx, imports_by_file, file_list, package_by_file,
        )
        confirmed.extend(call_confirmed)
        possible.extend(call_possible)
        unresolved.extend(call_unresolved)

        # Phase 3: Resolve framework (Gin) edges
        fw_confirmed, fw_possible, fw_unresolved = self._resolve_framework_edges(
            all_raw_edges, ctx, imports_by_file, file_list,
        )
        confirmed.extend(fw_confirmed)
        possible.extend(fw_possible)
        unresolved.extend(fw_unresolved)

        return ResolvedEdges(
            confirmed=confirmed,
            possible=possible,
            unresolved_candidates=unresolved,
        )

    # ── GraphContext ────────────────────────────────────────────────────

    def _build_context(
        self,
        symbols: list[GraphNode],
        file_list: list[str],
        package_by_file: dict[str, str],
    ) -> GraphContext:
        """Build a GraphContext from extracted symbols."""
        qual_to_id: dict[str, str] = {}
        name_to_ids: dict[str, list[str]] = {}
        file_to_ids: dict[str, list[str]] = {}

        for s in symbols:
            if s.qualified_name:
                qual_to_id[s.qualified_name] = s.id
            name_to_ids.setdefault(s.name, []).append(s.id)
            if s.file_path:
                file_to_ids.setdefault(s.file_path, []).append(s.id)

        return GraphContext(
            language_id=self.language_id,
            qual_to_id=qual_to_id,
            name_to_ids=name_to_ids,
            file_to_ids=file_to_ids,
            node_count=len(symbols),
        )

    # ── Import resolution ────────────────────────────────────────────────

    def _resolve_imports(
        self,
        raw_edges: list[GraphEdge],
        imports_by_file: dict[str, list[ImportInfo]],
        ctx: GraphContext,
        file_list: list[str],
        package_by_file: dict[str, str] = None,
    ) -> list[ResolvedEdge]:
        """Resolve import edges.

        Go imports are module-scoped. Internal packages within the same
        module should be resolved to project-internal nodes.
        """
        resolved: list[ResolvedEdge] = []
        package_by_file = package_by_file or {}

        for edge in raw_edges:
            if edge.type != EdgeType.imports:
                continue

            target = edge.target
            if not target.startswith("external:"):
                # Already internal — pass through as confirmed
                resolved.append(ResolvedEdge(
                    source=edge.source,
                    target=edge.target,
                    edge_type=edge.type,
                    confidence=edge.confidence,
                    resolution=edge.metadata.resolution if edge.metadata else Resolution.package_import_exact,
                    provenance=Provenance.IMPORT_RESOLVER,
                    evidence={"import_resolved": True},
                    source_location={"file_path": edge.source_location.file_path if edge.source_location else ""},
                ))
                continue

            # external:module_path
            external_path = target[len("external:"):]
            source_file = edge.source_location.file_path if edge.source_location else ""

            # Check if this is a stdlib import (always external)
            if self._is_stdlib(external_path):
                resolved.append(ResolvedEdge(
                    source=edge.source,
                    target=target,
                    edge_type=edge.type,
                    confidence=0.50,
                    resolution=Resolution.external_module,
                    provenance=Provenance.IMPORT_RESOLVER,
                    evidence={"import_path": external_path, "stdlib": True},
                    source_location={"file_path": source_file},
                ))
                continue

            # For external modules (github.com, etc.), mark as external
            if self._is_external_module(external_path):
                resolved.append(ResolvedEdge(
                    source=edge.source,
                    target=target,
                    edge_type=edge.type,
                    confidence=0.45,
                    resolution=Resolution.external_module,
                    provenance=Provenance.IMPORT_RESOLVER,
                    evidence={"import_path": external_path, "external_module": True},
                    source_location={"file_path": source_file},
                ))
                continue

            # It's a package import — try to find within the project
            # Package name is typically the last component of the import path
            pkg_name = external_path.split("/")[-1]

            # Try to find matching package nodes
            for qname, nid in ctx.qual_to_id.items():
                if qname == pkg_name or qname.startswith(pkg_name):
                    resolved.append(ResolvedEdge(
                        source=edge.source,
                        target=nid,
                        edge_type=edge.type,
                        confidence=0.85,
                        resolution=Resolution.package_import_exact,
                        provenance=Provenance.IMPORT_RESOLVER,
                        evidence={"import_path": external_path, "resolved_package": pkg_name},
                        source_location={"file_path": source_file},
                    ))
                    break
            else:
                # Not found — keep as external
                resolved.append(ResolvedEdge(
                    source=edge.source,
                    target=target,
                    edge_type=edge.type,
                    confidence=0.45,
                    resolution=Resolution.external_module,
                    provenance=Provenance.IMPORT_RESOLVER,
                    evidence={"import_path": external_path, "unresolved": True},
                    source_location={"file_path": source_file},
                ))

        return resolved

    # ── Call resolution ──────────────────────────────────────────────────

    def _resolve_calls(
        self,
        raw_edges: list[GraphEdge],
        ctx: GraphContext,
        imports_by_file: dict[str, list[ImportInfo]],
        file_list: list[str],
        package_by_file: dict[str, str],
    ) -> tuple[list[ResolvedEdge], list[ResolvedEdge], list[ResolvedEdge]]:
        """Resolve call edges to known symbols based on Go scoping rules."""
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved: list[ResolvedEdge] = []

        for edge in raw_edges:
            if edge.type != EdgeType.calls:
                continue

            target = edge.target
            source_file = edge.source_location.file_path if edge.source_location else ""
            resolution = edge.metadata.resolution if edge.metadata else Resolution.name_match_candidate

            # Already resolved (same_file_exact)
            if not target.startswith("unresolved:"):
                if resolution == Resolution.same_file_exact:
                    confirmed.append(ResolvedEdge(
                        source=edge.source,
                        target=edge.target,
                        edge_type=edge.type,
                        confidence=edge.confidence,
                        resolution=Resolution.same_file_exact,
                        provenance=Provenance.AST,
                        evidence={"same_file": True},
                        source_location={"file_path": source_file},
                    ))
                else:
                    possible.append(ResolvedEdge(
                        source=edge.source,
                        target=target,
                        edge_type=edge.type,
                        confidence=edge.confidence,
                        resolution=resolution,
                        provenance=Provenance.AST,
                        evidence={},
                    ))
                continue

            # Unresolved calls: "unresolved:expr"
            expr = target[len("unresolved:"):]

            # Check for pkg.Func() pattern
            if "." in expr:
                parts = expr.split(".", 1)
                pkg_or_obj = parts[0]
                func_name = parts[1]

                # Check if pkg_or_obj matches an imported package
                file_imports = imports_by_file.get(source_file, [])
                matched_import = None
                for imp in file_imports:
                    if imp.local_name == pkg_or_obj:
                        matched_import = imp
                        break

                if matched_import:
                    if matched_import.is_external:
                        # External package call — unresolved
                        unresolved.append(ResolvedEdge(
                            source=edge.source,
                            target=f"external:{matched_import.module_path}.{func_name}",
                            edge_type=edge.type,
                            confidence=0.30,
                            resolution=Resolution.external_module,
                            provenance=Provenance.IMPORT_RESOLVER,
                            evidence={
                                "import_path": matched_import.module_path,
                                "function": func_name,
                                "external": True,
                            },
                            source_location={"file_path": source_file},
                        ))
                    else:
                        # Internal package — resolved as package function
                        confirmed.append(ResolvedEdge(
                            source=edge.source,
                            target=f"unresolved:{matched_import.module_path}::{func_name}",
                            edge_type=edge.type,
                            confidence=0.90,
                            resolution=Resolution.package_function_exact,
                            provenance=Provenance.IMPORT_RESOLVER,
                            evidence={
                                "import_path": matched_import.module_path,
                                "function": func_name,
                            },
                            source_location={"file_path": source_file},
                        ))
                    continue

                # obj.Method() — check if obj is a known type with method
                # Look for receiver method match
                source_pkg = package_by_file.get(source_file, "")
                method_name = func_name
                receiver_candidates = []
                for qname, nid in ctx.qual_to_id.items():
                    if qname.endswith(f".{method_name}") and "::" in qname:
                        receiver_candidates.append((qname, nid))

                if receiver_candidates:
                    # Possible — receiver type known but may not match
                    for qname, nid in receiver_candidates[:3]:
                        receiver_type = qname.rsplit(".", 2)[-2] if qname.count(".") >= 2 else ""
                        possible.append(ResolvedEdge(
                            source=edge.source,
                            target=nid,
                            edge_type=edge.type,
                            confidence=0.40,
                            resolution=Resolution.unknown_receiver_method,
                            provenance=Provenance.HEURISTIC,
                            evidence={
                                "expression": expr,
                                "receiver_type": receiver_type,
                                "method": method_name,
                                "reason": "receiver type may not match actual object type",
                            },
                            source_location={"file_path": source_file},
                        ))
                    continue

                # Struct.Method() — possible embedded method candidate
                possible.append(ResolvedEdge(
                    source=edge.source,
                    target=f"unresolved:{expr}",
                    edge_type=edge.type,
                    confidence=0.30,
                    resolution=Resolution.embedded_method_candidate,
                    provenance=Provenance.HEURISTIC,
                    evidence={"reason": "could not resolve object.method call", "expression": expr},
                ))
                continue

            # Simple name: func()
            # Check same package
            source_pkg = package_by_file.get(source_file, "")
            name_matches = ctx.name_to_ids.get(expr, [])

            if len(name_matches) == 1:
                # Single match — check if same package
                match_id = name_matches[0]
                match_qname = ""
                for qname, nid in ctx.qual_to_id.items():
                    if nid == match_id:
                        match_qname = qname
                        break

                if match_qname:
                    # Possible — name-only match, not confirmed without import
                    possible.append(ResolvedEdge(
                        source=edge.source,
                        target=match_id,
                        edge_type=edge.type,
                        confidence=0.35,
                        resolution=Resolution.name_match_candidate,
                        provenance=Provenance.HEURISTIC,
                        evidence={
                            "name": expr,
                            "matched": match_qname,
                            "reason": "name-only match, not import-confirmed",
                        },
                        source_location={"file_path": source_file},
                    ))
                    continue

            if len(name_matches) > 1:
                # Multiple matches — ambiguous
                possible.append(ResolvedEdge(
                    source=edge.source,
                    target=name_matches[0],
                    edge_type=edge.type,
                    confidence=0.30,
                    resolution=Resolution.name_match_candidate,
                    provenance=Provenance.HEURISTIC,
                    evidence={
                        "name": expr,
                        "candidates": len(name_matches),
                        "reason": "multiple name matches, ambiguous",
                    },
                ))
                continue

            # No match found — unresolved
            unresolved.append(ResolvedEdge(
                source=edge.source,
                target=f"external:{expr}",
                edge_type=edge.type,
                confidence=0.20,
                resolution=Resolution.unknown_external,
                provenance=Provenance.HEURISTIC,
                evidence={"reason": "no matching symbol found for function call", "expression": expr},
            ))

        return confirmed, possible, unresolved

    # ── Framework edge resolution ────────────────────────────────────────

    _FRAMEWORK_ROUTE_RESOLVED: set[Resolution] = {
        Resolution.gin_route_resolved,
        Resolution.gin_group_route_resolved,
        Resolution.hertz_route_resolved,
        Resolution.hertz_group_route_resolved,
    }

    def _resolve_framework_edges(
        self,
        raw_edges: list[GraphEdge],
        ctx: GraphContext,
        imports_by_file: dict[str, list[ImportInfo]],
        file_list: list[str],
    ) -> tuple[list[ResolvedEdge], list[ResolvedEdge], list[ResolvedEdge]]:
        """Resolve Go framework-specific edges (routes_to, references)."""
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved: list[ResolvedEdge] = []

        framework_edge_types = {EdgeType.routes_to, EdgeType.references, EdgeType.depends_on}
        for edge in raw_edges:
            if edge.type not in framework_edge_types:
                continue
            meta = edge.metadata
            if meta is None:
                continue

            resolution = meta.resolution
            evidence = meta.evidence or {}
            framework_id = evidence.get("framework_id", "")

            if framework_id not in ("gin", "hertz"):
                continue

            source_file = edge.source_location.file_path if edge.source_location else ""

            # Inline handlers → possible tier
            if resolution in (Resolution.gin_inline_handler, Resolution.hertz_inline_handler):
                possible.append(self._resolved_from_edge(
                    edge, edge.target, resolution, Provenance.FRAMEWORK_RESOLVER, evidence,
                ))
                continue

            # Middleware chains → possible tier
            if resolution in (Resolution.gin_middleware_chain, Resolution.hertz_middleware_chain):
                possible.append(self._resolved_from_edge(
                    edge, edge.target, resolution, Provenance.FRAMEWORK_RESOLVER, evidence,
                ))
                continue

            # Resolved handler target
            target = edge.target
            if not target.startswith("unresolved:"):
                # Try to find in context
                target_found = target in ctx.qual_to_id or target in self._all_node_ids(ctx)
                if target_found or resolution in self._FRAMEWORK_ROUTE_RESOLVED:
                    confirmed.append(self._resolved_from_edge(
                        edge, target, resolution, Provenance.FRAMEWORK_RESOLVER, evidence,
                    ))
                else:
                    unresolved.append(self._resolved_from_edge(
                        edge, target, Resolution.unresolved, Provenance.FRAMEWORK_RESOLVER, evidence,
                    ))
                continue

            # Unresolved handler — try to resolve via imports
            expr = target[len("unresolved:"):]
            if "." in expr:
                # imported.Handler
                parts = expr.split(".", 1)
                pkg = parts[0]
                handler = parts[1]
                file_imports = imports_by_file.get(source_file, [])
                for imp in file_imports:
                    if imp.local_name == pkg:
                        if imp.is_external:
                            unresolved.append(self._resolved_from_edge(
                                edge, edge.target, Resolution.external_module,
                                Provenance.FRAMEWORK_RESOLVER,
                                {**evidence, "reason": "imported handler from external package"},
                            ))
                        else:
                            # Use the framework's route_resolved resolution
                            route_res = resolution if resolution in self._FRAMEWORK_ROUTE_RESOLVED else Resolution.gin_route_resolved
                            possible.append(self._resolved_from_edge(
                                edge, edge.target, route_res,
                                Provenance.FRAMEWORK_RESOLVER,
                                {**evidence, "reason": "imported handler, target file not indexed"},
                            ))
                        break
                else:
                    # Check if handler name matches any symbol
                    if handler in ctx.name_to_ids:
                        route_res = resolution if resolution in self._FRAMEWORK_ROUTE_RESOLVED else Resolution.gin_route_resolved
                        possible.append(self._resolved_from_edge(
                            edge, f"unresolved:{handler}", route_res,
                            Provenance.FRAMEWORK_RESOLVER,
                            {**evidence, "reason": "handler name match found"},
                        ))
                    else:
                        unresolved.append(self._resolved_from_edge(
                            edge, edge.target, Resolution.import_not_found,
                            Provenance.FRAMEWORK_RESOLVER,
                            {**evidence, "reason": "handler not found in project"},
                        ))
                continue

            # Simple name handler
            if expr in ctx.name_to_ids:
                handler_ids = ctx.name_to_ids[expr]
                # Find one in the same file
                same_file_id = None
                for hid in handler_ids:
                    for qname, nid in ctx.qual_to_id.items():
                        if nid == hid and source_file in qname:
                            same_file_id = hid
                            break
                    if same_file_id:
                        break

                route_res = resolution if resolution in self._FRAMEWORK_ROUTE_RESOLVED else Resolution.gin_route_resolved
                if same_file_id:
                    confirmed.append(self._resolved_from_edge(
                        edge, same_file_id, route_res,
                        Provenance.FRAMEWORK_RESOLVER,
                        {**evidence, "resolved_to": same_file_id},
                    ))
                else:
                    possible.append(self._resolved_from_edge(
                        edge, handler_ids[0], route_res,
                        Provenance.FRAMEWORK_RESOLVER,
                        {**evidence, "reason": "handler name match but different file"},
                    ))
            else:
                unresolved.append(self._resolved_from_edge(
                    edge, edge.target, Resolution.import_not_found,
                    Provenance.FRAMEWORK_RESOLVER,
                    {**evidence, "reason": "handler not found in project"},
                ))

        return confirmed, possible, unresolved

    # ── Helpers ──────────────────────────────────────────────────────────

    def _resolved_from_edge(
        self,
        edge: GraphEdge,
        target: str,
        resolution: Resolution,
        provenance: Provenance,
        evidence: dict[str, Any],
    ) -> ResolvedEdge:
        return ResolvedEdge(
            source=edge.source,
            target=target,
            edge_type=edge.type,
            confidence=getattr(edge, "confidence", 0.0) or 0.0,
            resolution=resolution,
            provenance=provenance,
            evidence=evidence,
            source_location=(
                {
                    "file_path": edge.source_location.file_path,
                    "line_start": edge.source_location.line_start,
                    "line_end": edge.source_location.line_end,
                }
                if edge.source_location else None
            ),
        )

    def _all_node_ids(self, ctx: GraphContext) -> set[str]:
        ids: set[str] = set(ctx.qual_to_id.values())
        for values in ctx.name_to_ids.values():
            ids.update(values)
        return ids

    def _is_stdlib(self, path: str) -> bool:
        """Check if a path is a Go standard library package."""
        if "/" not in path:
            return True  # single-component = stdlib
        first = path.split("/")[0]
        if "." in first:
            return False
        stdlib_prefixes = (
            "encoding/", "net/", "crypto/", "hash/",
            "html/", "text/", "mime/", "path/", "database/",
            "archive/", "compress/", "container/", "debug/",
            "go/", "image/", "index/", "internal/", "os/", "sync/",
            "testing/", "vendor/",
        )
        for pfx in stdlib_prefixes:
            if path.startswith(pfx):
                return True
        return False

    def _is_external_module(self, path: str) -> bool:
        """Check if a path looks like an external Go module."""
        if path.startswith("gopkg.in/"):
            return True
        if "/" in path:
            first = path.split("/")[0]
            if "." in first:
                return True
        return False
