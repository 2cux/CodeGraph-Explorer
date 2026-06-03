"""C# cross-file Resolver.

Resolves using/namespace-based symbol references, classifies edges
into confirmed / possible / unresolved tiers, resolves ASP.NET Core
framework edges.

Implements the ``Resolver`` interface from ``codegraph.language_support.resolver``.
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
from codegraph.language_support.extractor import ExtractorResult, ImportInfo


class CSharpResolver(Resolver):
    """C# cross-file resolver for using/namespace-based symbol resolution.

    Beta-level: regex-based, no Roslyn semantic analysis.
    """

    language_id: str = "csharp"

    def resolve(
        self,
        extractor_results: list[Any],
        graph_context: GraphContext | None = None,
        import_index: dict[str, Any] | None = None,
    ) -> ResolvedEdges:
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved: list[ResolvedEdge] = []

        all_symbols: list[GraphNode] = []
        all_raw_edges: list[GraphEdge] = []
        file_list: list[str] = []
        imports_by_file: dict[str, list[ImportInfo]] = {}
        namespaces_by_file: dict[str, str] = {}

        for er in extractor_results:
            r: ExtractorResult = er
            all_symbols.extend(r.symbols)
            raw = getattr(r, "_raw_edges", [])
            all_raw_edges.extend(raw)
            file_list.append(r.file_path)
            imports_by_file[r.file_path] = r.imports

            # Extract namespace from file's symbols
            for s in r.symbols:
                if s.metadata.get("kind") == "namespace" or s.type == NodeType.module:
                    namespaces_by_file[r.file_path] = s.name
                    break

        # Build GraphContext
        ctx = graph_context or self._build_context(all_symbols, file_list)

        # Phase 1: Resolve import edges
        resolved_imports = self._resolve_imports(
            all_raw_edges, imports_by_file, ctx, file_list,
        )
        confirmed.extend(resolved_imports)

        # Phase 2: Resolve call edges
        call_confirmed, call_possible, call_unresolved = self._resolve_calls(
            all_raw_edges, ctx, imports_by_file, namespaces_by_file, file_list,
        )
        confirmed.extend(call_confirmed)
        possible.extend(call_possible)
        unresolved.extend(call_unresolved)

        # Phase 3: Resolve inheritance / implementation edges
        inh_confirmed, inh_possible, inh_unresolved = self._resolve_inheritance(
            all_raw_edges, ctx, imports_by_file, namespaces_by_file,
        )
        confirmed.extend(inh_confirmed)
        possible.extend(inh_possible)
        unresolved.extend(inh_unresolved)

        # Phase 4: Resolve framework (ASP.NET Core) edges
        fw_confirmed, fw_possible, fw_unresolved = self._resolve_framework_edges(
            all_raw_edges, ctx,
        )
        confirmed.extend(fw_confirmed)
        possible.extend(fw_possible)
        unresolved.extend(fw_unresolved)

        return ResolvedEdges(
            confirmed=confirmed,
            possible=possible,
            unresolved_candidates=unresolved,
        )

    # ── GraphContext construction ────────────────────────────────────

    def _build_context(
        self, symbols: list[GraphNode], file_list: list[str]
    ) -> GraphContext:
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

    # ── Import resolution ────────────────────────────────────────────

    def _resolve_imports(
        self,
        raw_edges: list[GraphEdge],
        imports_by_file: dict[str, list[ImportInfo]],
        ctx: GraphContext,
        file_list: list[str],
    ) -> list[ResolvedEdge]:
        resolved: list[ResolvedEdge] = []

        for edge in raw_edges:
            if edge.type != EdgeType.imports:
                continue

            target = edge.target
            source_file = edge.source_location.file_path if edge.source_location else ""

            if target.startswith("external:"):
                # External package — mark as confirmed external
                external_name = target[len("external:"):]
                resolved.append(ResolvedEdge(
                    source=edge.source,
                    target=target,
                    edge_type=edge.type,
                    confidence=0.50,
                    resolution=Resolution.external_package,
                    provenance=Provenance.IMPORT_RESOLVER,
                    evidence={"external_namespace": external_name},
                    source_location={"file_path": source_file},
                ))
            elif target.startswith("namespace:"):
                ns_name = target[len("namespace:"):]
                # Try to find matching namespace in the project
                target_id = self._find_namespace_node(ctx, ns_name)
                if target_id:
                    resolved.append(ResolvedEdge(
                        source=edge.source,
                        target=target_id,
                        edge_type=edge.type,
                        confidence=0.88,
                        resolution=Resolution.using_namespace_exact,
                        provenance=Provenance.IMPORT_RESOLVER,
                        evidence={"namespace": ns_name},
                        source_location={"file_path": source_file},
                    ))
                else:
                    resolved.append(ResolvedEdge(
                        source=edge.source,
                        target=f"external:{ns_name}",
                        edge_type=edge.type,
                        confidence=0.50,
                        resolution=Resolution.external_package,
                        provenance=Provenance.IMPORT_RESOLVER,
                        evidence={"namespace": ns_name, "reason": "namespace not found in project"},
                        source_location={"file_path": source_file},
                    ))

        return resolved

    def _find_namespace_node(self, ctx: GraphContext, ns_name: str) -> str | None:
        """Find the node ID for a namespace."""
        for qname, nid in ctx.qual_to_id.items():
            if qname == ns_name:
                return nid
        return None

    # ── Call resolution ──────────────────────────────────────────────

    def _resolve_calls(
        self,
        raw_edges: list[GraphEdge],
        ctx: GraphContext,
        imports_by_file: dict[str, list[ImportInfo]],
        namespaces_by_file: dict[str, str],
        file_list: list[str],
    ) -> tuple[list[ResolvedEdge], list[ResolvedEdge], list[ResolvedEdge]]:
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved_list: list[ResolvedEdge] = []

        for edge in raw_edges:
            if edge.type != EdgeType.calls:
                continue

            target = edge.target
            resolution = edge.metadata.resolution if edge.metadata else Resolution.name_match_candidate
            source_file = edge.source_location.file_path if edge.source_location else ""
            file_namespace = namespaces_by_file.get(source_file, "")

            # Handle unresolved: prefix
            expr = target[len("unresolved:"):] if target.startswith("unresolved:") else target

            # this.method() calls
            if "this." in expr:
                method_name = expr.split("this.")[-1] if "this." in expr else expr
                if not target.startswith("unresolved:"):
                    # Already resolved same-file
                    confirmed.append(self._make_resolved(
                        edge, edge.target,
                        Resolution.this_method_exact, Provenance.AST,
                        evidence={"this_method": method_name, "source_file": source_file},
                    ))
                else:
                    # Try to find method in same file
                    found = self._find_in_file(ctx, source_file, method_name)
                    if found:
                        confirmed.append(self._make_resolved(
                            edge, found,
                            Resolution.this_method_exact, Provenance.AST,
                            evidence={"this_method": method_name, "source_file": source_file},
                        ))
                    else:
                        possible.append(self._make_resolved(
                            edge, f"unresolved:this.{method_name}",
                            Resolution.object_method_unknown, Provenance.HEURISTIC,
                            evidence={"reason": "class not resolved for this.method()"},
                        ))
                continue

            # base.method() calls
            if "base." in expr:
                method_name = expr.split("base.")[-1] if "base." in expr else expr
                if not target.startswith("unresolved:"):
                    confirmed.append(self._make_resolved(
                        edge, edge.target,
                        Resolution.base_method_exact, Provenance.AST,
                        evidence={"base_method": method_name, "source_file": source_file},
                    ))
                else:
                    possible.append(self._make_resolved(
                        edge, f"unresolved:base.{method_name}",
                        Resolution.object_method_unknown, Provenance.HEURISTIC,
                        evidence={"reason": "base class not resolved"},
                    ))
                continue

            # StaticClass.Method() or instance.Method() calls
            if "." in expr and not target.startswith("unresolved:"):
                confirmed.append(self._make_resolved(
                    edge, edge.target, resolution, Provenance.AST,
                    evidence={},
                ))
                continue

            if "." in expr:
                # obj.method() — check if obj is a known type
                parts = expr.split(".", 1)
                obj_name = parts[0]
                method_name = parts[1] if len(parts) > 1 else ""

                # Check if obj is imported via using or local variable
                file_imports = imports_by_file.get(source_file, [])
                matched_import = None
                for imp in file_imports:
                    if imp.local_name == obj_name:
                        matched_import = imp
                        break

                if matched_import:
                    if matched_import.is_external:
                        unresolved_list.append(self._make_resolved(
                            edge, f"external:{matched_import.module_path}.{method_name}",
                            Resolution.external_package, Provenance.IMPORT_RESOLVER,
                            evidence={"external_assembly": matched_import.module_path, "method": method_name},
                        ))
                    else:
                        # Try to resolve in target namespace
                        target_ns = matched_import.module_path
                        target_qname = f"{target_ns}.{obj_name}.{method_name}"
                        found = ctx.qual_to_id.get(target_qname)
                        if found:
                            confirmed.append(self._make_resolved(
                                edge, found,
                                Resolution.using_namespace_exact, Provenance.IMPORT_RESOLVER,
                                evidence={"using_namespace": target_ns, "method": method_name},
                            ))
                        else:
                            # Try namespace-local exact
                            ns_qname = f"{file_namespace}.{obj_name}.{method_name}" if file_namespace else ""
                            found_in_ns = ctx.qual_to_id.get(ns_qname) if ns_qname else None
                            if found_in_ns:
                                confirmed.append(self._make_resolved(
                                    edge, found_in_ns,
                                    Resolution.namespace_local_exact, Provenance.IMPORT_RESOLVER,
                                    evidence={"namespace": file_namespace, "method": method_name},
                                ))
                            else:
                                possible.append(self._make_resolved(
                                    edge, f"unresolved:{target_ns}.{method_name}",
                                    Resolution.unknown_type_method, Provenance.HEURISTIC,
                                    evidence={"reason": "method not found via using", "namespace": target_ns},
                                ))
                    continue

                # Try same-namespace resolution
                if file_namespace:
                    ns_qname = f"{file_namespace}.{obj_name}.{method_name}"
                    found = ctx.qual_to_id.get(ns_qname)
                    if found:
                        confirmed.append(self._make_resolved(
                            edge, found,
                            Resolution.namespace_local_exact, Provenance.HEURISTIC,
                            evidence={"namespace": file_namespace},
                        ))
                        continue

                # Check if obj matches a class name in the project
                class_candidates = ctx.name_to_ids.get(obj_name, [])
                if class_candidates:
                    # Find the method in one of the candidate classes
                    method_found = False
                    for cid in class_candidates:
                        method_qname = f"{cid}.{method_name}"
                        if method_qname in ctx.qual_to_id:
                            confirmed.append(self._make_resolved(
                                edge, ctx.qual_to_id[method_qname],
                                Resolution.static_method_exact, Provenance.HEURISTIC,
                                evidence={"class_name": obj_name, "method": method_name},
                            ))
                            method_found = True
                            break
                        # Also check by name
                        for qn, nid in ctx.qual_to_id.items():
                            if qn.endswith(f".{obj_name}.{method_name}") or qn.endswith(f"::{obj_name}.{method_name}"):
                                confirmed.append(self._make_resolved(
                                    edge, nid,
                                    Resolution.static_method_exact, Provenance.HEURISTIC,
                                    evidence={"class_name": obj_name, "method": method_name},
                                ))
                                method_found = True
                                break
                        if method_found:
                            break

                    if not method_found:
                        possible.append(self._make_resolved(
                            edge, f"unresolved:{expr}",
                            Resolution.unknown_type_method, Provenance.HEURISTIC,
                            evidence={"reason": "type resolved, method not found", "type": obj_name},
                        ))
                    continue

                # Unknown type — possible extension method or external
                possible.append(self._make_resolved(
                    edge, f"unresolved:{expr}",
                    Resolution.extension_method_candidate, Provenance.HEURISTIC,
                    evidence={"reason": "unknown type, possible extension method"},
                ))
                continue

            # Simple name — check if same-file
            if resolution == Resolution.same_file_exact:
                confirmed.append(self._make_resolved(
                    edge, edge.target,
                    resolution, Provenance.AST,
                    evidence={"same_file": True},
                ))
                continue

            # Name-only — lookup across project
            if target.startswith("unresolved:"):
                name = target[len("unresolved:"):]
            else:
                name = expr

            name_candidates = ctx.name_to_ids.get(name, [])
            if len(name_candidates) == 1:
                # Single unambiguous match
                node_id = name_candidates[0]
                # Check if in same namespace
                target_qname = None
                for qn, nid in ctx.qual_to_id.items():
                    if nid == node_id:
                        target_qname = qn
                        break

                if target_qname and file_namespace and target_qname.startswith(file_namespace):
                    confirmed.append(self._make_resolved(
                        edge, node_id,
                        Resolution.namespace_local_exact, Provenance.HEURISTIC,
                        evidence={"namespace": file_namespace, "unambiguous": True},
                    ))
                else:
                    possible.append(self._make_resolved(
                        edge, node_id,
                        Resolution.name_match_candidate, Provenance.HEURISTIC,
                        evidence={"reason": "single name match, different namespace"},
                    ))
            elif len(name_candidates) > 1:
                # Ambiguous — check same namespace first
                ns_match = None
                for nid in name_candidates:
                    for qn, qid in ctx.qual_to_id.items():
                        if qid == nid and file_namespace and qn.startswith(file_namespace):
                            ns_match = nid
                            break
                    if ns_match:
                        break

                if ns_match:
                    confirmed.append(self._make_resolved(
                        edge, ns_match,
                        Resolution.namespace_local_exact, Provenance.HEURISTIC,
                        evidence={"namespace": file_namespace, "ambiguous_but_namespace_match": True},
                    ))
                else:
                    possible.append(self._make_resolved(
                        edge, name_candidates[0],
                        Resolution.overloaded_method_candidate, Provenance.HEURISTIC,
                        evidence={"reason": f"ambiguous: {len(name_candidates)} candidates"},
                    ))
            else:
                unresolved_list.append(self._make_resolved(
                    edge, f"external:{name}",
                    Resolution.unknown_symbol, Provenance.HEURISTIC,
                    evidence={"reason": "no matching symbol found in project"},
                ))

        return confirmed, possible, unresolved_list

    # ── Inheritance resolution ───────────────────────────────────────

    def _resolve_inheritance(
        self,
        raw_edges: list[GraphEdge],
        ctx: GraphContext,
        imports_by_file: dict[str, list[ImportInfo]],
        namespaces_by_file: dict[str, str],
    ) -> tuple[list[ResolvedEdge], list[ResolvedEdge], list[ResolvedEdge]]:
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved_list: list[ResolvedEdge] = []

        for edge in raw_edges:
            if edge.type not in (EdgeType.inherits,):
                continue

            target = edge.target
            if not target.startswith("unresolved:"):
                confirmed.append(self._make_resolved(
                    edge, edge.target,
                    edge.metadata.resolution if edge.metadata else Resolution.exact_ast_match,
                    Provenance.AST,
                    evidence={},
                ))
                continue

            base_name = target[len("unresolved:"):]
            source_file = edge.source_location.file_path if edge.source_location else ""
            file_namespace = namespaces_by_file.get(source_file, "")

            # Try to find the base type in the project
            # 1. Same file
            same_file = self._find_in_file(ctx, source_file, base_name)
            if same_file:
                confirmed.append(self._make_resolved(
                    edge, same_file,
                    Resolution.same_file_exact, Provenance.AST,
                    evidence={"same_file": True},
                ))
                continue

            # 2. Same namespace
            if file_namespace:
                ns_qname = f"{file_namespace}.{base_name}"
                found = ctx.qual_to_id.get(ns_qname)
                if found:
                    confirmed.append(self._make_resolved(
                        edge, found,
                        Resolution.namespace_local_exact, Provenance.HEURISTIC,
                        evidence={"namespace": file_namespace},
                    ))
                    continue

            # 3. Via using imports
            file_imports = imports_by_file.get(source_file, [])
            found_via_using = False
            for imp in file_imports:
                if imp.is_external:
                    # External base class (e.g., ControllerBase)
                    if base_name in ("ControllerBase", "DbContext", "Hub", "PageModel",
                                     "RazorPage", "ComponentBase"):
                        unresolved_list.append(self._make_resolved(
                            edge, f"external:{imp.module_path}.{base_name}",
                            Resolution.external_package, Provenance.IMPORT_RESOLVER,
                            evidence={"external_assembly": imp.module_path, "base_type": base_name},
                        ))
                        found_via_using = True
                        break
                else:
                    ns_qname = f"{imp.module_path}.{base_name}"
                    found = ctx.qual_to_id.get(ns_qname)
                    if found:
                        confirmed.append(self._make_resolved(
                            edge, found,
                            Resolution.using_namespace_exact, Provenance.IMPORT_RESOLVER,
                            evidence={"using_namespace": imp.module_path},
                        ))
                        found_via_using = True
                        break

            if found_via_using:
                continue

            # 4. Name-only search
            name_candidates = ctx.name_to_ids.get(base_name, [])
            if name_candidates:
                # Prefer same namespace or same file
                best_match = None
                for nid in name_candidates:
                    for qn, qid in ctx.qual_to_id.items():
                        if qid == nid:
                            if file_namespace and qn.startswith(file_namespace):
                                best_match = nid
                                break
                            # Check same-file: node_id starts with file_path
                            if nid.startswith(source_file + "::"):
                                best_match = nid
                                break
                    if best_match:
                        break

                if best_match:
                    confirmed.append(self._make_resolved(
                        edge, best_match,
                        Resolution.namespace_local_exact if file_namespace else Resolution.same_file_exact,
                        Provenance.HEURISTIC,
                        evidence={"namespace": file_namespace, "same_file": not bool(file_namespace)},
                    ))
                else:
                    possible.append(self._make_resolved(
                        edge, name_candidates[0],
                        Resolution.interface_method_candidate, Provenance.HEURISTIC,
                        evidence={"reason": f"name-only match for {base_name}"},
                    ))
            else:
                unresolved_list.append(self._make_resolved(
                    edge, f"external:{base_name}",
                    Resolution.external_package, Provenance.HEURISTIC,
                    evidence={"reason": f"base type {base_name} not found"},
                ))

        return confirmed, possible, unresolved_list

    # ── Framework edge resolution ─────────────────────────────────────

    def _resolve_framework_edges(
        self,
        raw_edges: list[GraphEdge],
        ctx: GraphContext,
    ) -> tuple[list[ResolvedEdge], list[ResolvedEdge], list[ResolvedEdge]]:
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved_list: list[ResolvedEdge] = []

        for edge in raw_edges:
            if edge.type not in (EdgeType.routes_to, EdgeType.depends_on):
                continue

            meta = edge.metadata
            resolution = meta.resolution if meta else Resolution.framework_route_resolved
            evidence = dict(meta.evidence or {}) if meta else {}
            provenance = Provenance.FRAMEWORK_RESOLVER

            if resolution in {
                Resolution.inline_handler,
                Resolution.callback_candidate,
            }:
                possible.append(self._make_resolved(
                    edge, edge.target, resolution, provenance, evidence,
                ))
                continue

            if not edge.target.startswith("unresolved:"):
                target_id = ctx.qual_to_id.get(edge.target)
                if target_id or self._node_exists(ctx, edge.target):
                    confirmed.append(self._make_resolved(
                        edge, edge.target, resolution, provenance, evidence,
                    ))
                else:
                    confirmed.append(self._make_resolved(
                        edge, edge.target, resolution, provenance, evidence,
                    ))
                continue

            expr = edge.target[len("unresolved:"):]
            if "." in expr:
                possible.append(self._make_resolved(
                    edge, edge.target,
                    Resolution.object_method_unknown, provenance,
                    {**evidence, "reason": "object method type unknown"},
                ))
                continue

            name_candidates = ctx.name_to_ids.get(expr, [])
            if len(name_candidates) == 1:
                confirmed.append(self._make_resolved(
                    edge, name_candidates[0], resolution, provenance, evidence,
                ))
            elif len(name_candidates) > 1:
                possible.append(self._make_resolved(
                    edge, name_candidates[0],
                    Resolution.overloaded_method_candidate, provenance,
                    {**evidence, "reason": f"ambiguous: {len(name_candidates)} candidates"},
                ))
            else:
                unresolved_list.append(self._make_resolved(
                    edge, edge.target,
                    Resolution.unknown_symbol, provenance,
                    {**evidence, "reason": "framework target not found"},
                ))

        return confirmed, possible, unresolved_list

    # ── Helpers ───────────────────────────────────────────────────────

    def _make_resolved(
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

    def _find_in_file(self, ctx: GraphContext, file_path: str, name: str) -> str | None:
        """Find a symbol by name within a specific file."""
        if not file_path:
            return None
        exact = f"{file_path}::{name}"
        if exact in ctx.qual_to_id:
            return ctx.qual_to_id[exact]
        for qname, nid in ctx.qual_to_id.items():
            if qname.startswith(file_path + "::") and qname.endswith("." + name):
                return nid
            if qname == f"{file_path}::{name}":
                return nid
        return None

    def _node_exists(self, ctx: GraphContext, node_id: str) -> bool:
        """Check if a node ID exists in the graph context."""
        if node_id in ctx.qual_to_id.values():
            return True
        for values in ctx.name_to_ids.values():
            if node_id in values:
                return True
        return False
