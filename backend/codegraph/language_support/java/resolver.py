"""Java cross-file Resolver.

Resolves import paths, rewrites external targets to internal node IDs,
classifies edges into confirmed / possible / unresolved tiers, and
builds ``tested_by`` relationships.

Implements the ``Resolver`` interface.
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


class JavaResolver(Resolver):
    """Cross-file resolution for Java source files.

    Resolution tiers:
    - confirmed: same_file_exact, imported_class_exact, package_local_exact,
      this_method_exact, static_method_exact, annotation_resolved
    - possible: overloaded_method_candidate, interface_method_candidate,
      name_match_candidate, spring_bean_candidate
    - unresolved: external_package, unknown_type_method, dynamic_proxy,
      reflection_call, unknown_symbol
    """

    language_id: str = "java"

    def resolve(
        self,
        extractor_results: list[Any],
        graph_context: GraphContext | None = None,
        import_index: dict[str, Any] | None = None,
    ) -> ResolvedEdges:
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved: list[ResolvedEdge] = []

        # Gather all symbols and edges
        all_symbols: list[GraphNode] = []
        all_raw_edges: list[GraphEdge] = []
        file_list: list[str] = []
        imports_by_file: dict[str, list[ImportInfo]] = {}

        for er in extractor_results:
            r: ExtractorResult = er
            all_symbols.extend(r.symbols)
            raw = getattr(r, "_raw_edges", [])
            all_raw_edges.extend(raw)
            file_list.append(r.file_path)
            imports_by_file[r.file_path] = r.imports

        # Build context
        ctx = graph_context or self._build_context(all_symbols, file_list)

        # Phase 1: Resolve import edges
        import_confirmed = self._resolve_imports(
            all_raw_edges, imports_by_file, ctx, file_list
        )
        confirmed.extend(import_confirmed)

        # Phase 2: Resolve call edges
        call_confirmed, call_possible, call_unresolved = self._resolve_calls(
            all_raw_edges, ctx, imports_by_file, file_list
        )
        confirmed.extend(call_confirmed)
        possible.extend(call_possible)
        unresolved.extend(call_unresolved)

        # Phase 3: Resolve framework edges (Spring)
        fw_confirmed, fw_possible, fw_unresolved = self._resolve_framework_edges(
            all_raw_edges, ctx, imports_by_file, file_list
        )
        confirmed.extend(fw_confirmed)
        possible.extend(fw_possible)
        unresolved.extend(fw_unresolved)

        # Phase 4: Resolve inherits/implements edges
        inherit_confirmed, inherit_possible, inherit_unresolved = self._resolve_inheritance(
            all_raw_edges, ctx, imports_by_file, file_list
        )
        confirmed.extend(inherit_confirmed)
        possible.extend(inherit_possible)
        unresolved.extend(inherit_unresolved)

        # Phase 5: Build test relationships
        test_edges = self._build_test_relationships(all_symbols, all_raw_edges, ctx)
        confirmed.extend(test_edges)

        return ResolvedEdges(
            confirmed=confirmed,
            possible=possible,
            unresolved_candidates=unresolved,
        )

    # ── GraphContext ─────────────────────────────────────────────────────

    def _build_context(
        self, symbols: list[GraphNode], file_list: list[str]
    ) -> GraphContext:
        qual_to_id: dict[str, str] = {}
        name_to_ids: dict[str, list[str]] = {}
        file_to_ids: dict[str, list[str]] = {}

        for s in symbols:
            qual_to_id[s.qualified_name] = s.id
            name_to_ids.setdefault(s.name, []).append(s.id)
            if s.file_path:
                stem = Path(s.file_path).stem
                file_to_ids.setdefault(stem, []).append(s.id)

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
    ) -> list[ResolvedEdge]:
        """Resolve import edges: rewrite external: → internal node_id."""
        resolved: list[ResolvedEdge] = []

        for edge in raw_edges:
            if edge.type != EdgeType.imports:
                continue

            target = edge.target
            source_file = edge.source_location.file_path if edge.source_location else ""

            if target.startswith("external:"):
                external_name = target[len("external:"):]
                # Try to match imported class to project symbols
                parts = external_name.rsplit(".", 1)
                class_name = parts[-1] if parts else external_name

                # Find by name in project
                matched = False
                if class_name in ctx.name_to_ids:
                    candidates = ctx.name_to_ids[class_name]
                    for cid in candidates:
                        # Check if qualified_name matches the import path
                        for qname, nid in ctx.qual_to_id.items():
                            if nid == cid and external_name.replace(".", "/") in qname.replace("::", "/"):
                                resolved.append(ResolvedEdge(
                                    source=edge.source,
                                    target=cid,
                                    edge_type=edge.type,
                                    confidence=0.90,
                                    resolution=Resolution.imported_class_exact,
                                    provenance=Provenance.IMPORT_RESOLVER,
                                    evidence={"import_path": external_name, "resolved_class": class_name},
                                    source_location={"file_path": source_file},
                                ))
                                matched = True
                                break
                        if matched:
                            break

                if not matched:
                    resolved.append(ResolvedEdge(
                        source=edge.source,
                        target=target,
                        edge_type=edge.type,
                        confidence=0.50,
                        resolution=Resolution.external_package,
                        provenance=Provenance.IMPORT_RESOLVER,
                        evidence={"import_source": external_name},
                        source_location={"file_path": source_file},
                    ))
            else:
                # Already internal or unresolved
                resolution = edge.metadata.resolution if edge.metadata else Resolution.external_package
                resolved.append(ResolvedEdge(
                    source=edge.source,
                    target=edge.target,
                    edge_type=edge.type,
                    confidence=edge.confidence,
                    resolution=resolution,
                    provenance=Provenance.IMPORT_RESOLVER,
                    evidence={"import_resolved": not target.startswith("unresolved:")},
                    source_location={"file_path": source_file},
                ))

        return resolved

    # ── Call resolution ─────────────────────────────────────────────────

    def _resolve_calls(
        self,
        raw_edges: list[GraphEdge],
        ctx: GraphContext,
        imports_by_file: dict[str, list[ImportInfo]],
        file_list: list[str],
    ) -> tuple[list[ResolvedEdge], list[ResolvedEdge], list[ResolvedEdge]]:
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved: list[ResolvedEdge] = []

        for edge in raw_edges:
            if edge.type != EdgeType.calls:
                continue

            target = edge.target
            meta = edge.metadata
            resolution = meta.resolution if meta else Resolution.name_match_candidate
            source_file = edge.source_location.file_path if edge.source_location else ""

            actual_target = target
            if target.startswith("unresolved:"):
                actual_target = target[len("unresolved:"):]

            # this.method() calls
            if actual_target.startswith("this."):
                method_name = actual_target[5:]
                found = self._find_method_in_file(ctx, source_file, method_name)
                if found:
                    confirmed.append(ResolvedEdge(
                        source=edge.source,
                        target=found,
                        edge_type=edge.type,
                        confidence=0.90,
                        resolution=Resolution.this_method_exact,
                        provenance=Provenance.AST,
                        evidence={"this_method": method_name, "resolved_in": source_file},
                        source_location={"file_path": source_file},
                    ))
                else:
                    possible.append(ResolvedEdge(
                        source=edge.source,
                        target=target,
                        edge_type=edge.type,
                        confidence=0.35,
                        resolution=Resolution.unknown_type_method,
                        provenance=Provenance.HEURISTIC,
                        evidence={"reason": f"this.{method_name}() — method not found in file"},
                        source_location={"file_path": source_file},
                    ))
                continue

            # super.method() calls
            if actual_target.startswith("super."):
                method_name = actual_target[6:]
                possible.append(ResolvedEdge(
                    source=edge.source,
                    target=target,
                    edge_type=edge.type,
                    confidence=0.50,
                    resolution=Resolution.interface_method_candidate,
                    provenance=Provenance.HEURISTIC,
                    evidence={"reason": f"super.{method_name}() — parent class unknown"},
                    source_location={"file_path": source_file},
                ))
                continue

            # ClassName.staticMethod() calls
            if "." in actual_target and actual_target[0].isupper():
                parts = actual_target.split(".", 1)
                class_name = parts[0]
                method_name = parts[1] if len(parts) > 1 else ""

                # Try to find the class by import
                file_imports = imports_by_file.get(source_file, [])
                resolved_class = self._resolve_class_from_imports(
                    class_name, file_imports, ctx, file_list, source_file
                )

                if resolved_class:
                    # Find method in the class
                    class_prefix = resolved_class + "."
                    method_id = None
                    for qname, nid in ctx.qual_to_id.items():
                        if qname.startswith(class_prefix) and qname.endswith(f".{method_name}"):
                            method_id = nid
                            break

                    if method_id:
                        confirmed.append(ResolvedEdge(
                            source=edge.source,
                            target=method_id,
                            edge_type=edge.type,
                            confidence=0.90,
                            resolution=Resolution.static_method_exact,
                            provenance=Provenance.AST,
                            evidence={
                                "class_name": class_name,
                                "method_name": method_name,
                                "resolved_class": resolved_class,
                            },
                            source_location={"file_path": source_file},
                        ))
                        continue

                # Static call — class found or not
                possible.append(ResolvedEdge(
                    source=edge.source,
                    target=target,
                    edge_type=edge.type,
                    confidence=0.40 if not resolved_class else 0.70,
                    resolution=Resolution.name_match_candidate if not resolved_class else Resolution.static_method_exact,
                    provenance=Provenance.AST,
                    evidence={"reason": f"static method {actual_target}() — target not fully resolved"},
                    source_location={"file_path": source_file},
                ))
                continue

            # obj.method() — dynamic dispatch
            if "." in actual_target:
                parts = actual_target.split(".", 1)
                obj_var = parts[0]
                method_name = parts[1] if len(parts) > 1 else ""
                unresolved.append(ResolvedEdge(
                    source=edge.source,
                    target=target,
                    edge_type=edge.type,
                    confidence=0.30,
                    resolution=Resolution.unknown_type_method,
                    provenance=Provenance.HEURISTIC,
                    evidence={"reason": f"instance method call {obj_var}.{method_name}() — type unknown"},
                    source_location={"file_path": source_file},
                ))
                continue

            # Simple function call
            if resolution == Resolution.name_match_candidate:
                # Try to find matching method in same file or package
                name_matches = ctx.name_to_ids.get(actual_target, [])

                # Filter: only same-package or same-file matches
                same_file_matches = [
                    nid for nid in name_matches
                    for qname, qid in ctx.qual_to_id.items()
                    if qid == nid and source_file in qname
                ]

                if same_file_matches:
                    confirmed.append(ResolvedEdge(
                        source=edge.source,
                        target=same_file_matches[0],
                        edge_type=edge.type,
                        confidence=0.95,
                        resolution=Resolution.same_file_exact,
                        provenance=Provenance.AST,
                        evidence={"same_file": source_file},
                        source_location={"file_path": source_file},
                    ))
                elif name_matches:
                    possible.append(ResolvedEdge(
                        source=edge.source,
                        target=name_matches[0],
                        edge_type=edge.type,
                        confidence=0.35,
                        resolution=Resolution.name_match_candidate,
                        provenance=Provenance.HEURISTIC,
                        evidence={"name_matches": len(name_matches), "reason": "name match, not same file"},
                        source_location={"file_path": source_file},
                    ))
                else:
                    unresolved.append(ResolvedEdge(
                        source=edge.source,
                        target=f"external:{actual_target}",
                        edge_type=edge.type,
                        confidence=0.20,
                        resolution=Resolution.unknown_symbol,
                        provenance=Provenance.HEURISTIC,
                        evidence={"reason": "no matching symbol found"},
                        source_location={"file_path": source_file},
                    ))
                continue

            # Fallback based on resolution tier
            if is_confirmed_resolution(resolution):
                confirmed.append(ResolvedEdge(
                    source=edge.source,
                    target=edge.target,
                    edge_type=edge.type,
                    confidence=edge.confidence,
                    resolution=resolution,
                    provenance=Provenance.AST,
                    evidence={},
                    source_location={"file_path": source_file},
                ))
            elif is_possible_resolution(resolution):
                possible.append(ResolvedEdge(
                    source=edge.source,
                    target=edge.target,
                    edge_type=edge.type,
                    confidence=edge.confidence,
                    resolution=resolution,
                    provenance=Provenance.HEURISTIC,
                    evidence={},
                    source_location={"file_path": source_file},
                ))
            else:
                unresolved.append(ResolvedEdge(
                    source=edge.source,
                    target=edge.target,
                    edge_type=edge.type,
                    confidence=edge.confidence,
                    resolution=resolution,
                    provenance=Provenance.HEURISTIC,
                    evidence={},
                    source_location={"file_path": source_file},
                ))

        return confirmed, possible, unresolved

    # ── Framework edge resolution ───────────────────────────────────────

    def _resolve_framework_edges(
        self,
        raw_edges: list[GraphEdge],
        ctx: GraphContext,
        imports_by_file: dict[str, list[ImportInfo]],
        file_list: list[str],
    ) -> tuple[list[ResolvedEdge], list[ResolvedEdge], list[ResolvedEdge]]:
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved: list[ResolvedEdge] = []

        fw_types = {EdgeType.routes_to, EdgeType.depends_on, EdgeType.references}
        for edge in raw_edges:
            if edge.type not in fw_types:
                continue

            meta = edge.metadata
            resolution = meta.resolution if meta else Resolution.framework_route_resolved
            provenance = Provenance.FRAMEWORK_RESOLVER
            evidence = dict(meta.evidence or {}) if meta and meta.evidence else {}
            source_file = edge.source_location.file_path if edge.source_location else evidence.get("file_path", "")

            target = edge.target

            # Resolve "unresolved:TypeName" targets for depends_on edges
            if target.startswith("unresolved:"):
                expr = target[len("unresolved:"):]
                if edge.type == EdgeType.depends_on:
                    # Try to find the dependency class
                    target_id = self._resolve_dependency(
                        expr, source_file, ctx, imports_by_file, file_list
                    )
                    if target_id:
                        confirmed.append(self._re(
                            edge, target_id, resolution, provenance, evidence, source_file
                        ))
                    else:
                        possible.append(self._re(
                            edge, target, Resolution.spring_bean_candidate, provenance,
                            {**evidence, "reason": f"dependency {expr} not found"},
                            source_file,
                        ))
                    continue
                elif edge.type == EdgeType.references and resolution in {
                    Resolution.spring_rest_controller,
                    Resolution.spring_controller,
                    Resolution.spring_service,
                    Resolution.spring_repository,
                    Resolution.spring_component,
                }:
                    confirmed.append(self._re(
                        edge, target, resolution, provenance, evidence, source_file
                    ))
                    continue
                elif edge.type == EdgeType.routes_to and resolution == Resolution.spring_route_resolved:
                    # Check if handler method exists
                    if expr in ctx.qual_to_id:
                        confirmed.append(self._re(
                            edge, expr, resolution, provenance, evidence, source_file
                        ))
                    else:
                        possible.append(self._re(
                            edge, target, Resolution.spring_overloaded_route, provenance,
                            {**evidence, "reason": "route handler method not in index"},
                            source_file,
                        ))
                    continue

            # Non-unresolved target
            if target in ctx.qual_to_id or target in self._all_node_ids(ctx):
                if is_confirmed_resolution(resolution):
                    confirmed.append(self._re(edge, target, resolution, provenance, evidence, source_file))
                elif is_possible_resolution(resolution):
                    possible.append(self._re(edge, target, resolution, provenance, evidence, source_file))
                else:
                    unresolved.append(self._re(edge, target, Resolution.unresolved, provenance, evidence, source_file))
            else:
                unresolved.append(self._re(
                    edge, target, Resolution.unresolved, provenance,
                    {**evidence, "reason": "target not found in graph"},
                    source_file,
                ))

        return confirmed, possible, unresolved

    # ── Inheritance resolution ──────────────────────────────────────────

    def _resolve_inheritance(
        self,
        raw_edges: list[GraphEdge],
        ctx: GraphContext,
        imports_by_file: dict[str, list[ImportInfo]],
        file_list: list[str],
    ) -> tuple[list[ResolvedEdge], list[ResolvedEdge], list[ResolvedEdge]]:
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved: list[ResolvedEdge] = []

        for edge in raw_edges:
            if edge.type not in (EdgeType.inherits,):
                continue

            source_file = edge.source_location.file_path if edge.source_location else ""
            target = edge.target
            actual_target = target[len("unresolved:"):] if target.startswith("unresolved:") else target

            # Try to find the parent class/interface
            name_matches = ctx.name_to_ids.get(actual_target, [])
            file_imports = imports_by_file.get(source_file, [])

            # Check imports first
            resolved = self._resolve_class_from_imports(
                actual_target, file_imports, ctx, file_list, source_file
            )

            if resolved:
                confirmed.append(ResolvedEdge(
                    source=edge.source,
                    target=resolved,
                    edge_type=edge.type,
                    confidence=0.85,
                    resolution=Resolution.imported_class_exact,
                    provenance=Provenance.IMPORT_RESOLVER,
                    evidence={"parent_class": actual_target, "resolved": resolved},
                    source_location={"file_path": source_file},
                ))
            elif name_matches:
                # Could be same-package
                possible.append(ResolvedEdge(
                    source=edge.source,
                    target=name_matches[0],
                    edge_type=edge.type,
                    confidence=0.40,
                    resolution=Resolution.package_local_exact,
                    provenance=Provenance.HEURISTIC,
                    evidence={"reason": f"class {actual_target} matched by name only"},
                    source_location={"file_path": source_file},
                ))
            else:
                unresolved.append(ResolvedEdge(
                    source=edge.source,
                    target=f"external:{actual_target}",
                    edge_type=edge.type,
                    confidence=0.30,
                    resolution=Resolution.external_package,
                    provenance=Provenance.HEURISTIC,
                    evidence={"reason": f"class {actual_target} not found in project"},
                    source_location={"file_path": source_file},
                ))

        return confirmed, possible, unresolved

    # ── Test relationships ───────────────────────────────────────────────

    def _build_test_relationships(
        self,
        symbols: list[GraphNode],
        raw_edges: list[GraphEdge],
        ctx: GraphContext,
    ) -> list[ResolvedEdge]:
        """Build tested_by edges for Java test files."""
        edges: list[ResolvedEdge] = []

        test_symbols = [s for s in symbols if s.type == NodeType.test or "test" in s.tags]
        test_files = {s.file_path for s in test_symbols}

        for test_file in test_files:
            stem = Path(test_file).stem
            # Remove Test suffix/prefix
            for suffix in ("Test", "Tests", "IT", "ITest"):
                if stem.endswith(suffix):
                    target_stem = stem[:-len(suffix)]
                    break
            else:
                target_stem = stem

            for src_file in {s.file_path for s in symbols if s.file_path}:
                if not src_file:
                    continue
                src_stem = Path(src_file).stem
                if src_stem == target_stem:
                    for s in symbols:
                        if s.file_path == src_file and s.type in (NodeType.class_, NodeType.controller, NodeType.service):
                            edges.append(ResolvedEdge(
                                source=s.id,
                                target="",
                                edge_type=EdgeType.tested_by,
                                confidence=0.55,
                                resolution=Resolution.test_file_heuristic,
                                provenance=Provenance.HEURISTIC,
                                evidence={
                                    "test_file": test_file,
                                    "source_file": src_file,
                                    "strategy": "file_name_match",
                                },
                            ))
                            break

        return edges

    # ── Helpers ──────────────────────────────────────────────────────────

    def _find_method_in_file(
        self, ctx: GraphContext, file_path: str, method_name: str
    ) -> str | None:
        """Find a method node in the graph by file and method name."""
        for qname, nid in ctx.qual_to_id.items():
            if qname.startswith(file_path + "::") and qname.endswith("." + method_name):
                return nid
        return None

    def _resolve_class_from_imports(
        self,
        class_name: str,
        file_imports: list[ImportInfo],
        ctx: GraphContext,
        file_list: list[str],
        source_file: str,
    ) -> str | None:
        """Resolve a class name by checking imports and project symbols."""
        # Check if imported
        for imp in file_imports:
            if imp.local_name == class_name or imp.imported_name == class_name:
                # Find by qualified name in project
                for qname, nid in ctx.qual_to_id.items():
                    name_part = qname.rsplit("::", 1)[-1] if "::" in qname else qname
                    if name_part == class_name:
                        return nid
                return None

        # Try same-package match
        package_prefix = source_file.rsplit("/", 1)[0] if "/" in source_file else ""
        for qname, nid in ctx.qual_to_id.items():
            if package_prefix and qname.startswith(package_prefix) and qname.endswith("::" + class_name):
                return nid

        return None

    def _resolve_dependency(
        self,
        type_name: str,
        source_file: str,
        ctx: GraphContext,
        imports_by_file: dict[str, list[ImportInfo]],
        file_list: list[str],
    ) -> str | None:
        """Resolve a dependency type name to a project symbol."""
        file_imports = imports_by_file.get(source_file, [])

        # Check imports
        for imp in file_imports:
            if imp.local_name == type_name:
                for qname, nid in ctx.qual_to_id.items():
                    if qname.endswith("::" + type_name):
                        return nid

        # Check name matches
        name_matches = ctx.name_to_ids.get(type_name, [])
        if name_matches:
            return name_matches[0]

        return None

    def _all_node_ids(self, ctx: GraphContext) -> set[str]:
        ids: set[str] = set(ctx.qual_to_id.values())
        for values in ctx.name_to_ids.values():
            ids.update(values)
        return ids

    def _re(
        self,
        edge: GraphEdge,
        target: str,
        resolution: Resolution,
        provenance: Provenance,
        evidence: dict[str, Any],
        source_file: str = "",
    ) -> ResolvedEdge:
        """Create a ResolvedEdge from a GraphEdge."""
        return ResolvedEdge(
            source=edge.source,
            target=target,
            edge_type=edge.type,
            confidence=getattr(edge, "confidence", 0.0) or 0.0,
            resolution=resolution,
            provenance=provenance,
            evidence=evidence,
            source_location={
                "file_path": source_file or (
                    edge.source_location.file_path if edge.source_location else ""
                ),
            },
        )
