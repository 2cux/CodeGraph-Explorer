"""Tests for enriched drop/auto-correct classification in validation.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.graph.validation import validate_graph


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_indexer_accumulator():
    """Drain the indexer diagnostic accumulator before each test.

    The module-level ``_indexer_drops`` / ``_indexer_auto_corrected`` lists
    in ``graph_builder`` persist across tests.  If a previous test ran
    ``build_index``, stale drops would inflate the ``total_edges`` count
    in ``edge_health`` when ``validate_graph`` drains them.
    """
    try:
        from codegraph.indexer.graph_builder import get_indexer_diagnostics
        get_indexer_diagnostics()  # drain and discard
    except ImportError:
        pass


# ── Helpers ────────────────────────────────────────────────────────────


def _make_node(
    node_id: str,
    name: str = "",
    node_type: str = "function",
    file_path: str = "app/module.py",
) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "name": name or node_id.split("::")[-1],
        "file_path": file_path,
        "module": file_path.replace("/", ".").removesuffix(".py"),
        "tags": [],
        "metadata": {},
    }


def _make_edge(
    edge_id: str,
    source: str,
    target: str,
    edge_type: str = "calls",
    confidence: float = 1.0,
    resolution: str = "import_resolved",
) -> dict:
    return {
        "id": edge_id,
        "type": edge_type,
        "source": source,
        "target": target,
        "confidence": confidence,
        "metadata": {"resolution": resolution, "reason": ""},
    }


@pytest.fixture
def tmp_cg_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".codegraph"
    d.mkdir()
    return d


# ── Tests ──────────────────────────────────────────────────────────────


class TestEdgeHealthReturned:
    """validate_graph() should return an edge_health key."""

    def test_edge_health_present(self, tmp_cg_dir: Path):
        nodes = [_make_node("n1", "foo"), _make_node("n2", "bar")]
        edges = [_make_edge("e1", "n1", "n2")]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        assert "edge_health" in report
        eh = report["edge_health"]
        assert eh["total_edges"] == 1
        assert eh["total_dropped"] == 0
        assert eh["total_auto_corrected"] == 0


class TestImplementsNormalized:
    """Java 'implements' edges should be normalized to 'inherits', not dropped."""

    def test_implements_normalized_not_dropped(self, tmp_cg_dir: Path):
        nodes = [
            _make_node("n1", "Foo", "class"),
            _make_node("n2", "Bar", "class"),
        ]
        edges = [_make_edge("e1", "n1", "n2", edge_type="implements")]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        eh = report["edge_health"]
        assert eh["total_dropped"] == 0
        assert eh["total_auto_corrected"] == 1

        # Check the edge type was corrected
        auto = report["auto_corrected"]
        assert len(auto) == 1
        assert auto[0]["reason"] == "type_alias_corrected"
        assert auto[0]["original_value"] == "implements"
        assert auto[0]["corrected_value"] == "inherits"


class TestDanglingEdgeSplitReasons:
    """Dangling edges should be split into source/target/both reasons."""

    def test_missing_target(self, tmp_cg_dir: Path):
        nodes = [_make_node("n1", "Foo")]
        edges = [_make_edge("e1", "n1", "n_missing")]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        by_reason = _by_reason(report, "dropped")
        assert by_reason.get("missing_target") == 1

    def test_missing_source(self, tmp_cg_dir: Path):
        nodes = [_make_node("n1", "Foo")]
        edges = [_make_edge("e1", "n_missing2", "n1")]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        by_reason = _by_reason(report, "dropped")
        assert by_reason.get("missing_source") == 1

    def test_missing_both(self, tmp_cg_dir: Path):
        nodes = [_make_node("n1", "Foo")]
        edges = [_make_edge("e1", "n_missing1", "n_missing2")]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        by_reason = _by_reason(report, "dropped")
        assert by_reason.get("missing_both") == 1


class TestDroppedRatioEdgeBased:
    """Dropped ratio should be dropped / (edge_count + dropped), not per symbol."""

    def test_ratio_is_edge_based(self, tmp_cg_dir: Path):
        nodes = [_make_node("n1", "Foo")]
        edges = [
            _make_edge("e1", "n1", "n1"),           # valid
            _make_edge("e2", "n1", "n_missing"),     # dropped
            _make_edge("e3", "n1", "n_missing2"),    # dropped
        ]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        eh = report["edge_health"]
        # 2 dropped / 3 total = 0.6667
        assert eh["dropped_ratio"] == pytest.approx(2 / 3, abs=0.01)


class TestNodeTypeNormalization:
    """Non-canonical node types should be normalized, not warned."""

    def test_func_normalized(self, tmp_cg_dir: Path):
        nodes = [_make_node("n1", "foo", node_type="func")]
        edges = [_make_edge("e1", "n1", "n1")]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        ac = report["auto_corrected"]
        assert any(a["reason"] == "symbol_kind_normalized" for a in ac)

    def test_interface_normalized(self, tmp_cg_dir: Path):
        nodes = [_make_node("n1", "MyInterface", node_type="interface")]
        edges = [_make_edge("e1", "n1", "n1")]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        ac = report["auto_corrected"]
        assert any(a["reason"] == "symbol_kind_normalized" for a in ac)


class TestByReasonBreakdown:
    """The edge_health should contain by_reason breakdowns."""

    def test_dropped_by_reason_structure(self, tmp_cg_dir: Path):
        nodes = [_make_node("n1", "Foo")]
        edges = [
            _make_edge("e1", "n1", "n1"),           # valid
            _make_edge("e2", "n1", "n_missing"),     # missing_target
            _make_edge("e3", "n1", "n_missing2"),    # missing_target
            _make_edge("e4", "n_missing3", "n1"),    # missing_source
        ]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        eh = report["edge_health"]
        dropped_br = eh["dropped_by_reason"]
        assert len(dropped_br) > 0

        # Should be sorted by count descending
        assert dropped_br[0]["count"] >= dropped_br[-1]["count"]

        # Each entry should have reason, count, top_examples
        for br in dropped_br:
            assert "reason" in br
            assert "count" in br
            assert "top_examples" in br
            assert br["count"] == len(br["top_examples"])

    def test_auto_corrected_by_reason_structure(self, tmp_cg_dir: Path):
        nodes = [_make_node("n1", "Foo"), _make_node("n2", "Bar")]
        edges = [
            _make_edge("e1", "n1", "n2", edge_type="implements"),
            _make_edge("e2", "n1", "n2", edge_type="extends"),
        ]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        eh = report["edge_health"]
        ac_br = eh["auto_corrected_by_reason"]
        assert len(ac_br) > 0
        for br in ac_br:
            assert "reason" in br
            assert "count" in br
            assert "top_examples" in br


class TestImpactAndActions:
    """Impact assessment and suggested actions should be generated."""

    def test_impact_assessment_present(self, tmp_cg_dir: Path):
        nodes = [_make_node("n1", "Foo")]
        edges = [
            _make_edge("e1", "n1", "n1"),
            _make_edge("e2", "n1", "n_missing"),
        ]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        eh = report["edge_health"]
        assert "impact_assessment" in eh
        assert len(eh["impact_assessment"]) > 0

    def test_suggested_actions_present(self, tmp_cg_dir: Path):
        nodes = [_make_node("n1", "Foo")]
        edges = [_make_edge("e1", "n1", "n1")]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        eh = report["edge_health"]
        assert "suggested_actions" in eh
        assert isinstance(eh["suggested_actions"], list)
        assert len(eh["suggested_actions"]) > 0


class TestInvalidEdgeTypeDropped:
    """Truly invalid edge types (no alias match) should still be dropped."""

    def test_invalid_edge_type_dropped(self, tmp_cg_dir: Path):
        nodes = [
            _make_node("n1", "Foo"),
            _make_node("n2", "Bar"),
        ]
        edges = [_make_edge("e1", "n1", "n2", edge_type="completely_invalid")]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        by_reason = _by_reason(report, "dropped")
        assert by_reason.get("invalid_edge_type") == 1


class TestBackwardCompat:
    """Legacy fields should still be present."""

    def test_issue_key_present(self, tmp_cg_dir: Path):
        """Dropped/auto-corrected items should have both 'issue' and 'reason'."""
        nodes = [_make_node("n1", "Foo")]
        edges = [_make_edge("e1", "n1", "n_missing")]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        for d in report["dropped"]:
            assert "issue" in d
            assert "reason" in d
            assert d["issue"] == d["reason"]

    def test_edge_health_in_return(self, tmp_cg_dir: Path):
        """Return dict should have both legacy keys and edge_health."""
        nodes = [_make_node("n1", "Foo"), _make_node("n2", "Bar")]
        edges = [_make_edge("e1", "n1", "n2")]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        # Legacy keys
        assert "auto_corrected" in report
        assert "dropped" in report
        assert "warnings" in report
        assert "fatal" in report
        assert "stats" in report
        # New key
        assert "edge_health" in report


class TestPathNormalization:
    """Backslash paths should be normalized to forward slashes."""

    def test_backslash_path_normalized(self, tmp_cg_dir: Path):
        nodes = [_make_node("n1", "Foo", file_path="app\\module.py")]
        edges = [_make_edge("e1", "n1", "n1")]
        report = validate_graph(tmp_cg_dir, tmp_cg_dir.parent,
                                nodes=nodes, edges=edges)
        ac = report["auto_corrected"]
        assert any(
            a["reason"] == "path_normalized"
            and a["original_value"] == "app\\module.py"
            and a["corrected_value"] == "app/module.py"
            for a in ac
        )


# ── Helpers ────────────────────────────────────────────────────────────


def _by_reason(report: dict, list_key: str) -> dict[str, int]:
    """Count entries in report[list_key] by reason."""
    counts: dict[str, int] = {}
    for entry in report.get(list_key, []):
        reason = entry.get("reason", "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return counts
