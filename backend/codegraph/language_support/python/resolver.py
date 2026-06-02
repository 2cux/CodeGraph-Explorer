"""Python language resolver — wraps existing cross-file resolution.

Adds ``provenance`` to every confirmed edge and classifies edges into
confirmed / possible / unresolved_candidates tiers based on their
``Resolution`` value.
"""

from __future__ import annotations

from typing import Any

from codegraph.language_support.resolver import (
    Resolver,
    ResolvedEdge,
    ResolvedEdges,
    GraphContext,
    Provenance,
)

from codegraph.graph.models import (
    GraphNode,
    GraphEdge,
    EdgeType,
    EdgeLocation,
    EdgeMetadata,
    NodeType,
    Resolution,
)
from codegraph.graph.confidence import get_confidence, is_low_confidence
from codegraph.graph.impact import (
    is_confirmed_resolution,
    is_possible_resolution,
    is_unresolved_resolution,
)


# ── Provenance assignment ──────────────────────────────────────────────

# Resolutions that come from direct AST observation
_AST_RESOLUTIONS: set[Resolution] = {
    Resolution.exact_ast_match,
    Resolution.same_file_exact,
    Resolution.self_method_resolved,
    Resolution.class_method_resolved,
    Resolution.direct_test_call,
    Resolution.config_constant_detected,
}

# Resolutions that come from import tracing
_IMPORT_RESOLVER_RESOLUTIONS: set[Resolution] = {
    Resolution.import_resolved,
    Resolution.imported_function_exact,
    Resolution.imported_function_alias,
    Resolution.imported_module_attribute,
    Resolution.relative_import_resolved,
    Resolution.constructor_call_resolved,
    Resolution.local_instance_resolved,
    Resolution.module_instance_resolved,
    Resolution.self_attribute_instance_resolved,
    Resolution.same_module_fallback,
}

# Resolutions that come from type analysis
_TYPE_RESOLVER_RESOLUTIONS: set[Resolution] = {
    Resolution.parameter_type_hint_resolved,
    Resolution.type_hint_resolved,
}

# Resolutions that come from framework conventions
_FRAMEWORK_RESOLVER_RESOLUTIONS: set[Resolution] = {
    Resolution.fastapi_route_decorator,
    Resolution.flask_route_decorator,
    Resolution.framework_route_resolved,
    Resolution.pydantic_model_detected,
    Resolution.dataclass_model_detected,
    Resolution.sqlalchemy_model_detected,
    Resolution.config_class_detected,
    Resolution.repository_name_match,
    Resolution.store_name_match,
    Resolution.persistence_name_match,
    Resolution.model_field_match,
    Resolution.config_field_match,
    Resolution.django_view_heuristic,
}

# Resolutions that come from heuristics
_HEURISTIC_RESOLUTIONS: set[Resolution] = {
    Resolution.test_name_heuristic,
    Resolution.test_file_heuristic,
    Resolution.suggested_test,
    Resolution.name_match_candidate,
    Resolution.filename_heuristic,
    Resolution.docstring_reference,
    Resolution.attribute_guess,
    Resolution.test_import_match,
}


def assign_provenance(edge: GraphEdge) -> Provenance:
    """Determine the provenance of an edge based on its type and resolution.

    Structural edges (contains, defined_in, imports) always come from AST.
    Call edges are classified by their resolution strategy.
    Test edges use the heuristic provenance for name/file matching.
    """
    # Structural edges are always AST
    if edge.type in (EdgeType.contains, EdgeType.defined_in, EdgeType.imports):
        return Provenance.AST

    res = edge.metadata.resolution if edge.metadata else None
    if res is None:
        return Provenance.HEURISTIC

    if res in _AST_RESOLUTIONS:
        return Provenance.AST
    if res in _IMPORT_RESOLVER_RESOLUTIONS:
        return Provenance.IMPORT_RESOLVER
    if res in _TYPE_RESOLVER_RESOLUTIONS:
        return Provenance.TYPE_RESOLVER
    if res in _FRAMEWORK_RESOLVER_RESOLUTIONS:
        return Provenance.FRAMEWORK_RESOLVER
    if res in _HEURISTIC_RESOLUTIONS:
        return Provenance.HEURISTIC

    # Test edges: direct_test_call → AST, others → heuristic
    if edge.type == EdgeType.tested_by:
        if res == Resolution.direct_test_call:
            return Provenance.AST
        return Provenance.HEURISTIC

    # Calls edges not caught above — likely import_resolver
    if edge.type == EdgeType.calls:
        return Provenance.IMPORT_RESOLVER

    # Default
    return Provenance.HEURISTIC


def _edge_source_location(edge: GraphEdge) -> dict[str, Any] | None:
    """Extract source location from an edge for ResolvedEdge."""
    if edge.source_location:
        return {
            "file_path": edge.source_location.file_path,
            "line_start": edge.source_location.line_start,
            "line_end": edge.source_location.line_end,
        }
    return None


def _edge_evidence(edge: GraphEdge) -> dict[str, Any]:
    """Extract evidence from EdgeMetadata."""
    if edge.metadata and edge.metadata.evidence:
        return dict(edge.metadata.evidence)
    return {}


# ── Python Resolver ─────────────────────────────────────────────────────

class PythonResolver(Resolver):
    """Cross-file edge resolver for Python.

    Wraps the existing resolution pipeline:
    1. ``_resolve_external_edges`` — rewrites ``external:`` targets to
       internal node IDs using qualified_name → node_id lookup.
    2. ``_build_test_relationships`` — adds ``tested_by`` edges via
       direct calls, name heuristics, and file matching.

    Every confirmed edge receives ``provenance``, ``resolution``,
    ``confidence``, and ``evidence``.
    """

    language_id = "python"

    def resolve(self,
                extractor_results: list[Any],
                graph_context: GraphContext | None = None,
                import_index: dict[str, Any] | None = None,
                ) -> ResolvedEdges:
        """Resolve cross-file edges from Python extraction results.

        Args:
            extractor_results: List of :class:`~codegraph.language_support.extractor.ExtractorResult`
                               from :class:`PythonExtractor`.
            graph_context: Pre-built graph context with qual_to_id mappings.
                           If ``None``, built from the extraction results.
            import_index: Unused for Python (resolution is self-contained).

        Returns:
            :class:`ResolvedEdges` with confirmed, possible, and
            unresolved_candidates tiers.
        """
        # Collect all nodes and edges from extraction results
        all_nodes: list[GraphNode] = []
        all_edges: list[GraphEdge] = []

        for result in extractor_results:
            all_nodes.extend(result.symbols)
            # Edges from the extractor are stored as internal state
            # (the per-file call + structural edges). For Phase 1, we
            # reconstruct them from the ExtractorResult symbols + the
            # raw graph edges produced by the extractor.
            if hasattr(result, '_raw_edges'):
                all_edges.extend(result._raw_edges)

        # Build graph context if not provided
        if graph_context is None:
            graph_context = self._build_context(all_nodes)

        # Phase 1: Resolve external edges (external: → internal node IDs)
        all_edges = self._resolve_external_edges(all_edges, all_nodes)

        # Phase 2: Build test relationships
        test_edges = self._build_test_relationships(all_nodes, all_edges)
        all_edges.extend(test_edges)

        # Deduplicate
        all_edges = self._deduplicate_edges(all_edges)

        # Classify into confirmed / possible / unresolved
        return self._classify_edges(all_edges)

    # ── Context building ──────────────────────────────────────────────

    def _build_context(self, nodes: list[GraphNode]) -> GraphContext:
        """Build a :class:`GraphContext` from the collected nodes."""
        _TYPE_PRIORITY = {
            NodeType.import_: 0,
            NodeType.external_symbol: 0,
            NodeType.module: 1,
            NodeType.file: 1,
            NodeType.method: 3,
            NodeType.function: 3,
            NodeType.class_: 3,
            NodeType.test: 3,
            NodeType.repository: 0,
        }

        qual_to_id: dict[str, str] = {}
        qual_type: dict[str, NodeType] = {}
        name_to_ids: dict[str, list[str]] = {}
        file_to_ids: dict[str, list[str]] = {}

        _callable_types = {NodeType.function, NodeType.method, NodeType.class_}

        for node in nodes:
            # qual_to_id (prefer function/class/method over import)
            if node.qualified_name and not node.id.startswith("external:"):
                prev = qual_type.get(node.qualified_name)
                new_prio = _TYPE_PRIORITY.get(node.type, 0)
                prev_prio = _TYPE_PRIORITY.get(prev, -1) if prev else -1
                if prev is None or new_prio > prev_prio:
                    qual_to_id[node.qualified_name] = node.id
                    qual_type[node.qualified_name] = node.type

            # name_to_ids (for test name heuristic)
            if node.type in _callable_types and not node.id.startswith("external:"):
                name_to_ids.setdefault(node.name, []).append(node.id)

            # file_to_ids (for test file heuristic)
            if node.type in _callable_types and node.file_path:
                stem = node.file_path.rsplit("/", 1)[-1].replace(".py", "")
                file_to_ids.setdefault(stem, []).append(node.id)

        return GraphContext(
            language_id=self.language_id,
            qual_to_id=qual_to_id,
            name_to_ids=name_to_ids,
            file_to_ids=file_to_ids,
            node_count=len(nodes),
        )

    # ── External edge resolution ──────────────────────────────────────

    def _resolve_external_edges(self, edges: list[GraphEdge],
                                 nodes: list[GraphNode]) -> list[GraphEdge]:
        """Rewrite ``external:module.qualname`` targets to internal node IDs.

        Mirrors :func:`codegraph.indexer.graph_builder._resolve_external_edges`.
        """
        _TYPE_PRIORITY = {
            NodeType.import_: 0, NodeType.external_symbol: 0,
            NodeType.module: 1, NodeType.file: 1,
            NodeType.method: 3, NodeType.function: 3,
            NodeType.class_: 3, NodeType.test: 3,
            NodeType.repository: 0,
        }
        qual_to_id: dict[str, str] = {}
        qual_type: dict[str, NodeType] = {}
        for node in nodes:
            if node.qualified_name and not node.id.startswith("external:"):
                prev = qual_type.get(node.qualified_name)
                new_prio = _TYPE_PRIORITY.get(node.type, 0)
                prev_prio = _TYPE_PRIORITY.get(prev, -1) if prev else -1
                if prev is None or new_prio > prev_prio:
                    qual_to_id[node.qualified_name] = node.id
                    qual_type[node.qualified_name] = node.type

        _NO_REWRITE_RESOLUTIONS: set[Resolution] = {
            Resolution.name_match_candidate,
            Resolution.unknown_external,
            Resolution.external_symbol,
            Resolution.unresolved,
            Resolution.filename_heuristic,
            Resolution.docstring_reference,
        }

        for edge in edges:
            key = edge.type.value if hasattr(edge.type, 'value') else str(edge.type)
            if key != "calls":
                continue
            if not edge.target.startswith("external:"):
                continue

            edge_res = edge.metadata.resolution if edge.metadata else None
            if edge_res in _NO_REWRITE_RESOLUTIONS:
                continue

            qual_name = edge.target[len("external:"):]
            if qual_name in qual_to_id:
                edge.target = qual_to_id[qual_name]

        return edges

    # ── Test relationships ────────────────────────────────────────────

    def _build_test_relationships(self, nodes: list[GraphNode],
                                   edges: list[GraphEdge]) -> list[GraphEdge]:
        """Generate ``tested_by`` edges from target symbols to their tests.

        Mirrors :func:`codegraph.indexer.graph_builder._build_test_relationships`.
        """
        import itertools
        _counter = itertools.count(1)

        def _next_eid() -> str:
            return f"edge_{next(_counter):04d}"

        test_edges: list[GraphEdge] = []

        test_nodes = [n for n in nodes if n.type == NodeType.test]
        if not test_nodes:
            return test_edges

        _callable_types = {NodeType.function, NodeType.method, NodeType.class_}
        name_to_ids: dict[str, list[str]] = {}
        for n in nodes:
            if n.type in _callable_types and not n.id.startswith("external:"):
                name_to_ids.setdefault(n.name, []).append(n.id)

        file_to_ids: dict[str, list[str]] = {}
        for n in nodes:
            if n.type in _callable_types and n.file_path:
                stem = n.file_path.rsplit("/", 1)[-1].replace(".py", "")
                file_to_ids.setdefault(stem, []).append(n.id)

        covered: set[tuple[str, str]] = set()

        def _add_edge(target_id: str, test_id: str, confidence: float,
                      resolution: Resolution, reason: str = "",
                      evidence: dict | None = None) -> None:
            key = (target_id, test_id)
            if key in covered:
                return
            covered.add(key)
            test_edges.append(GraphEdge(
                id=_next_eid(),
                type=EdgeType.tested_by,
                source=target_id,
                target=test_id,
                confidence=confidence,
                metadata=EdgeMetadata(
                    resolution=resolution,
                    reason=reason,
                    evidence=evidence,
                ),
            ))

        for test_node in test_nodes:
            # Strategy 1: Direct calls from test → target
            for edge in edges:
                if edge.type != EdgeType.calls:
                    continue
                if edge.source == test_node.id:
                    target_node_id = edge.target
                    if not target_node_id.startswith("external:"):
                        res = Resolution.direct_test_call
                        _add_edge(
                            target_node_id, test_node.id,
                            get_confidence(res), res,
                            reason=f"Test `{test_node.name}` directly calls this symbol.",
                            evidence={
                                "test_symbol": test_node.id,
                                "target_symbol": target_node_id,
                                "call_expr": edge.metadata.call_expr if edge.metadata else None,
                            },
                        )

            # Strategy 2: Name heuristic
            test_name = test_node.name
            if test_name.startswith("test_"):
                remainder = test_name[len("test_"):]
                parts = remainder.split("_")
                for i in range(len(parts), 0, -1):
                    candidate = "_".join(parts[:i])
                    if candidate in name_to_ids:
                        for sym_id in name_to_ids[candidate]:
                            res = Resolution.test_name_heuristic
                            _add_edge(
                                sym_id, test_node.id,
                                get_confidence(res), res,
                                reason=f"Test name `{test_node.name}` contains symbol name `{candidate}`.",
                                evidence={
                                    "test_name": test_node.name,
                                    "matched_candidate": candidate,
                                    "matched_symbol_id": sym_id,
                                },
                            )
                        break

            # Strategy 3: File name match
            test_file = test_node.file_path
            if test_file:
                test_stem = test_file.rsplit("/", 1)[-1].replace(".py", "")
                for prefix in ("test_",):
                    if test_stem.startswith(prefix):
                        module_stem = test_stem[len(prefix):]
                        if module_stem in file_to_ids:
                            for sym_id in file_to_ids[module_stem]:
                                res = Resolution.test_file_heuristic
                                _add_edge(
                                    sym_id, test_node.id,
                                    get_confidence(res), res,
                                    reason=f"Test file `{test_file}` matches module `{module_stem}`.",
                                    evidence={
                                        "test_file": test_file,
                                        "matched_module": module_stem,
                                    },
                                )
                        break
                if test_stem.endswith("_test"):
                    module_stem = test_stem[:-len("_test")]
                    if module_stem in file_to_ids:
                        for sym_id in file_to_ids[module_stem]:
                            res = Resolution.test_file_heuristic
                            _add_edge(
                                sym_id, test_node.id,
                                get_confidence(res), res,
                                reason=f"Test file `{test_file}` matches module `{module_stem}` via _test suffix.",
                                evidence={
                                    "test_file": test_file,
                                    "matched_module": module_stem,
                                },
                            )

        return test_edges

    # ── Edge deduplication ────────────────────────────────────────────

    def _deduplicate_edges(self, edges: list[GraphEdge]) -> list[GraphEdge]:
        """Remove duplicate edges sharing the same (source, target, type)."""
        seen: set[tuple[str, str, str]] = set()
        result: list[GraphEdge] = []
        for e in edges:
            key = (e.source, e.target, e.type.value if hasattr(e.type, 'value') else str(e.type))
            if key not in seen:
                seen.add(key)
                result.append(e)
        return result

    # ── Edge classification ───────────────────────────────────────────

    def _classify_edges(self, edges: list[GraphEdge]) -> ResolvedEdges:
        """Classify edges into confirmed / possible / unresolved_candidates.

        Uses the same resolution-tier logic as
        :mod:`codegraph.graph.impact`.
        """
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved: list[ResolvedEdge] = []

        for edge in edges:
            res = edge.metadata.resolution if edge.metadata else None
            if res is None:
                # Edges without resolution go to possible
                possible.append(self._to_resolved_edge(edge))
                continue

            if is_confirmed_resolution(res):
                confirmed.append(self._to_resolved_edge(edge))
            elif is_possible_resolution(res):
                possible.append(self._to_resolved_edge(edge))
            else:
                unresolved.append(self._to_resolved_edge(edge))

        return ResolvedEdges(
            confirmed=confirmed,
            possible=possible,
            unresolved_candidates=unresolved,
        )

    def _to_resolved_edge(self, edge: GraphEdge) -> ResolvedEdge:
        """Convert a :class:`GraphEdge` to a :class:`ResolvedEdge` with provenance."""
        res = edge.metadata.resolution if edge.metadata else Resolution.unresolved
        return ResolvedEdge(
            source=edge.source,
            target=edge.target,
            edge_type=edge.type,
            confidence=edge.confidence,
            resolution=res,
            provenance=assign_provenance(edge),
            evidence=_edge_evidence(edge),
            source_location=_edge_source_location(edge),
            metadata=edge.metadata,
        )
