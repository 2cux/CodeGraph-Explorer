"""Tests for graph/normalize.py — edge type and node type alias mapping."""

from __future__ import annotations

import pytest

from codegraph.graph.models import AutoCorrectReason, EdgeType, NodeType
from codegraph.graph.normalize import normalize_edge_type, normalize_node_type


class TestNormalizeEdgeType:
    """Edge type alias normalization."""

    def test_canonical_passthrough(self):
        """Canonical types should pass through unchanged, no correction."""
        canonical, correction = normalize_edge_type("calls")
        assert canonical == EdgeType.calls
        assert correction is None

    def test_implements_alias(self):
        """'implements' should normalize to inherits (Java bug fix)."""
        canonical, correction = normalize_edge_type("implements")
        assert canonical == EdgeType.inherits
        assert correction == AutoCorrectReason.type_alias_corrected

    def test_extends_alias(self):
        """'extends' should normalize to inherits."""
        canonical, correction = normalize_edge_type("extends")
        assert canonical == EdgeType.inherits
        assert correction == AutoCorrectReason.type_alias_corrected

    def test_uses_alias(self):
        """'uses' should normalize to depends_on."""
        canonical, correction = normalize_edge_type("uses")
        assert canonical == EdgeType.depends_on
        assert correction == AutoCorrectReason.type_alias_corrected

    def test_tested_alias(self):
        """'tested' should normalize to tested_by."""
        canonical, correction = normalize_edge_type("tested")
        assert canonical == EdgeType.tested_by
        assert correction == AutoCorrectReason.type_alias_corrected

    def test_routes_alias(self):
        """'routes' should normalize to routes_to."""
        canonical, correction = normalize_edge_type("routes")
        assert canonical == EdgeType.routes_to
        assert correction == AutoCorrectReason.type_alias_corrected

    def test_singular_forms(self):
        """Singular forms should normalize to plural canonical forms."""
        pairs = [
            ("import", EdgeType.imports),
            ("call", EdgeType.calls),
            ("inherit", EdgeType.inherits),
            ("reference", EdgeType.references),
            ("contain", EdgeType.contains),
        ]
        for raw, expected in pairs:
            canonical, correction = normalize_edge_type(raw)
            assert canonical == expected, f"'{raw}' should map to {expected}"
            assert correction == AutoCorrectReason.type_alias_corrected

    def test_alternate_spellings(self):
        """Alternate spellings should normalize."""
        pairs = [
            ("define_in", EdgeType.defined_in),
            ("depend_on", EdgeType.depends_on),
            ("route_to", EdgeType.routes_to),
            ("test_by", EdgeType.tested_by),
        ]
        for raw, expected in pairs:
            canonical, correction = normalize_edge_type(raw)
            assert canonical == expected, f"'{raw}' should map to {expected}"
            assert correction is not None

    def test_case_insensitive(self):
        """Normalization should be case-insensitive."""
        canonical, correction = normalize_edge_type("IMPLEMENTS")
        assert canonical == EdgeType.inherits
        assert correction == AutoCorrectReason.type_alias_corrected

    def test_whitespace_handling(self):
        """Leading/trailing whitespace should be stripped."""
        canonical, correction = normalize_edge_type("  calls  ")
        assert canonical == EdgeType.calls
        assert correction is None  # already canonical after strip

    def test_invalid_type_returns_none(self):
        """Completely unrecognized types should return None."""
        canonical, correction = normalize_edge_type("nonsense_type_xyz")
        assert canonical is None
        assert correction is None

    def test_empty_string(self):
        """Empty string should return None."""
        canonical, correction = normalize_edge_type("")
        assert canonical is None
        assert correction is None

    def test_non_string_input(self):
        """Non-string input should return None gracefully."""
        canonical, correction = normalize_edge_type(42)  # type: ignore
        assert canonical is None
        assert correction is None

    def test_all_canonical_types_passthrough(self):
        """Every canonical EdgeType value should map to itself with no correction."""
        for etype in EdgeType:
            canonical, correction = normalize_edge_type(etype.value)
            assert canonical == etype
            assert correction is None


class TestNormalizeNodeType:
    """Node type alias normalization."""

    def test_canonical_passthrough(self):
        """Canonical types should pass through unchanged."""
        canonical, correction = normalize_node_type("function")
        assert canonical == NodeType.function
        assert correction is None

    def test_func_alias(self):
        """'func' should normalize to function."""
        canonical, correction = normalize_node_type("func")
        assert canonical == NodeType.function
        assert correction == AutoCorrectReason.symbol_kind_normalized

    def test_cls_alias(self):
        """'cls' should normalize to class."""
        canonical, correction = normalize_node_type("cls")
        assert canonical == NodeType.class_
        assert correction == AutoCorrectReason.symbol_kind_normalized

    def test_interface_alias(self):
        """'interface' should normalize to class."""
        canonical, correction = normalize_node_type("interface")
        assert canonical == NodeType.class_
        assert correction == AutoCorrectReason.symbol_kind_normalized

    def test_enum_alias(self):
        """'enum' should normalize to class."""
        canonical, correction = normalize_node_type("enum")
        assert canonical == NodeType.class_
        assert correction == AutoCorrectReason.symbol_kind_normalized

    def test_struct_alias(self):
        """'struct' should normalize to class."""
        canonical, correction = normalize_node_type("struct")
        assert canonical == NodeType.class_
        assert correction == AutoCorrectReason.symbol_kind_normalized

    def test_case_insensitive(self):
        """Normalization should be case-insensitive."""
        canonical, correction = normalize_node_type("FUNC")
        assert canonical == NodeType.function
        assert correction == AutoCorrectReason.symbol_kind_normalized

    def test_invalid_type_returns_none(self):
        """Unrecognized node types should return None."""
        canonical, correction = normalize_node_type("nonsense_node_type")
        assert canonical is None
        assert correction is None

    def test_all_canonical_types_passthrough(self):
        """Every canonical NodeType value should map to itself."""
        for ntype in NodeType:
            canonical, correction = normalize_node_type(ntype.value)
            assert canonical == ntype
            assert correction is None
