"""Tests for PythonResolver — provenance, confirmed/possible classification."""

import pytest

from codegraph.language_support.resolver import (
    Provenance,
    ResolvedEdge,
    ResolvedEdges,
    GraphContext,
)
from codegraph.language_support.python.extractor import PythonExtractor
from codegraph.language_support.python.resolver import PythonResolver, assign_provenance
from codegraph.graph.models import (
    GraphNode,
    GraphEdge,
    EdgeType,
    EdgeMetadata,
    NodeType,
    Resolution,
    Location,
)
from codegraph.graph.confidence import get_confidence


class TestProvenanceAssignment:
    def test_structural_edges_are_ast(self):
        """contains, defined_in, imports edges must have AST provenance."""
        edge = GraphEdge(
            id="e1", type=EdgeType.contains,
            source="file.py", target="file.py::func",
            metadata=EdgeMetadata(resolution=Resolution.exact_ast_match),
        )
        assert assign_provenance(edge) == Provenance.AST

    def test_defined_in_is_ast(self):
        edge = GraphEdge(
            id="e1", type=EdgeType.defined_in,
            source="file.py::func", target="module:file",
            metadata=EdgeMetadata(resolution=Resolution.exact_ast_match),
        )
        assert assign_provenance(edge) == Provenance.AST

    def test_imports_is_ast(self):
        edge = GraphEdge(
            id="e1", type=EdgeType.imports,
            source="file.py", target="file.py::import.os",
            metadata=EdgeMetadata(resolution=Resolution.exact_ast_match),
        )
        assert assign_provenance(edge) == Provenance.AST

    def test_same_file_call_is_ast(self):
        edge = GraphEdge(
            id="e1", type=EdgeType.calls,
            source="file.py::greet", target="file.py::hello",
            metadata=EdgeMetadata(resolution=Resolution.same_file_exact),
        )
        assert assign_provenance(edge) == Provenance.AST

    def test_imported_call_is_import_resolver(self):
        edge = GraphEdge(
            id="e1", type=EdgeType.calls,
            source="file.py::main", target="other.py::login",
            metadata=EdgeMetadata(resolution=Resolution.imported_function_exact),
        )
        assert assign_provenance(edge) == Provenance.IMPORT_RESOLVER

    def test_type_hint_is_type_resolver(self):
        edge = GraphEdge(
            id="e1", type=EdgeType.calls,
            source="file.py::process", target="file.py::Service.method",
            metadata=EdgeMetadata(resolution=Resolution.parameter_type_hint_resolved),
        )
        assert assign_provenance(edge) == Provenance.TYPE_RESOLVER

    def test_fastapi_route_is_framework_resolver(self):
        edge = GraphEdge(
            id="e1", type=EdgeType.references,
            source="file.py::router", target="file.py::handler",
            metadata=EdgeMetadata(resolution=Resolution.fastapi_route_decorator),
        )
        assert assign_provenance(edge) == Provenance.FRAMEWORK_RESOLVER

    def test_test_name_heuristic_is_heuristic(self):
        edge = GraphEdge(
            id="e1", type=EdgeType.tested_by,
            source="auth.py::login", target="tests/test_auth.py::test_login",
            metadata=EdgeMetadata(resolution=Resolution.test_name_heuristic),
        )
        assert assign_provenance(edge) == Provenance.HEURISTIC

    def test_direct_test_call_is_ast(self):
        edge = GraphEdge(
            id="e1", type=EdgeType.tested_by,
            source="auth.py::login", target="tests/test_auth.py::test_login",
            metadata=EdgeMetadata(resolution=Resolution.direct_test_call),
        )
        assert assign_provenance(edge) == Provenance.AST

    def test_edge_without_metadata_defaults_heuristic(self):
        edge = GraphEdge(
            id="e1", type=EdgeType.calls,
            source="a.py::f", target="b.py::g",
        )
        assert assign_provenance(edge) == Provenance.HEURISTIC


class TestResolvedEdge:
    def test_create_confirmed_edge(self):
        re = ResolvedEdge(
            source="file.py::func",
            target="other.py::helper",
            edge_type=EdgeType.calls,
            confidence=0.90,
            resolution=Resolution.imported_function_exact,
            provenance=Provenance.IMPORT_RESOLVER,
            evidence={"import_path": "other.helper"},
        )
        assert re.provenance == Provenance.IMPORT_RESOLVER
        assert re.confidence == 0.90
        assert re.evidence == {"import_path": "other.helper"}


class TestResolvedEdges:
    def test_empty(self):
        re = ResolvedEdges()
        assert re.confirmed == []
        assert re.possible == []
        assert re.unresolved_candidates == []

    def test_tier_separation(self):
        re = ResolvedEdges(
            confirmed=[
                ResolvedEdge(
                    source="a", target="b", edge_type=EdgeType.calls,
                    confidence=0.95, resolution=Resolution.same_file_exact,
                    provenance=Provenance.AST,
                ),
            ],
            possible=[
                ResolvedEdge(
                    source="c", target="d", edge_type=EdgeType.calls,
                    confidence=0.35, resolution=Resolution.name_match_candidate,
                    provenance=Provenance.HEURISTIC,
                ),
            ],
            unresolved_candidates=[
                ResolvedEdge(
                    source="e", target="f", edge_type=EdgeType.calls,
                    confidence=0.15, resolution=Resolution.dynamic_getattr,
                    provenance=Provenance.HEURISTIC,
                ),
            ],
        )
        assert len(re.confirmed) == 1
        assert len(re.possible) == 1
        assert len(re.unresolved_candidates) == 1
        # Name-only must NOT be in confirmed
        assert re.possible[0].resolution == Resolution.name_match_candidate
        assert re.possible[0].provenance == Provenance.HEURISTIC

    def test_all_confirmed_edges_have_provenance(self):
        """Every confirmed edge must carry provenance."""
        confirmed = [
            ResolvedEdge(
                source=f"s{i}", target=f"t{i}", edge_type=EdgeType.calls,
                confidence=0.90, resolution=Resolution.imported_function_exact,
                provenance=Provenance.IMPORT_RESOLVER,
                evidence={"k": "v"},
            )
            for i in range(3)
        ]
        re = ResolvedEdges(confirmed=confirmed)
        for e in re.confirmed:
            assert e.provenance is not None
            assert e.resolution is not None
            assert e.confidence > 0
            assert isinstance(e.evidence, dict)


class TestPythonResolver:
    def test_resolve_empty(self):
        resolver = PythonResolver()
        result = resolver.resolve([])
        assert isinstance(result, ResolvedEdges)
        assert result.confirmed == []
        assert result.possible == []
        assert result.unresolved_candidates == []

    def test_classify_edges_confirmed_vs_possible(self):
        """Name-only resolutions must go to possible, not confirmed."""
        resolver = PythonResolver()
        confirmed_edge = GraphEdge(
            id="e1", type=EdgeType.calls,
            source="a.py::f", target="b.py::g",
            confidence=0.90,
            metadata=EdgeMetadata(
                resolution=Resolution.imported_function_exact,
            ),
        )
        name_only_edge = GraphEdge(
            id="e2", type=EdgeType.calls,
            source="c.py::x", target="d.py::y",
            confidence=0.35,
            metadata=EdgeMetadata(
                resolution=Resolution.name_match_candidate,
            ),
        )
        result = resolver._classify_edges([confirmed_edge, name_only_edge])
        assert len(result.confirmed) == 1
        assert len(result.possible) == 1
        assert result.confirmed[0].resolution == Resolution.imported_function_exact
        assert result.possible[0].resolution == Resolution.name_match_candidate
        # Name-only must NOT be in confirmed
        confirmed_resolutions = {e.resolution for e in result.confirmed}
        assert Resolution.name_match_candidate not in confirmed_resolutions
