"""Tests for test_coverage_signal — detection, signal computation, and edge cases."""

import pytest
from pathlib import Path

from codegraph.graph.models import (
    GraphNode, GraphEdge, NodeType, EdgeType, Location,
    EdgeMetadata, Resolution,
)
from codegraph.graph.test_coverage import (
    detect_test_files,
    compute_test_coverage_signal,
    TESTED_BY_HIGH_CONFIDENCE_THRESHOLD,
)


# ═══════════════════════════════════════════════════════════════════════════════
# detect_test_files tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectTestFiles:
    """Filesystem test file detection using path/name heuristics."""

    def test_python_test_files(self, tmp_path: Path):
        """test_*.py and *_test.py in tests/ directory are detected."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_auth.py").write_text("def test_login(): pass")
        (tests_dir / "auth_test.py").write_text("def test(): pass")
        (tests_dir / "conftest.py").write_text("import pytest")

        result = detect_test_files(str(tmp_path))
        assert result["count"] >= 2
        assert "test_auth.py" in str(result["sample_files"])

    def test_typescript_test_files(self, tmp_path: Path):
        """*.test.ts and *.spec.ts files are detected."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "foo.test.ts").write_text("test('foo', () => {})")
        (src_dir / "bar.spec.ts").write_text("describe('bar', () => {})")

        result = detect_test_files(str(tmp_path))
        assert result["count"] >= 2

    def test_go_test_files(self, tmp_path: Path):
        """*_test.go files are detected."""
        (tmp_path / "handler_test.go").write_text("package main")

        result = detect_test_files(str(tmp_path))
        assert result["count"] >= 1

    def test_java_test_files(self, tmp_path: Path):
        """FooTest.java files are detected."""
        tests_dir = tmp_path / "src" / "test"
        tests_dir.mkdir(parents=True)
        (tests_dir / "FooTest.java").write_text("class FooTest {}")

        result = detect_test_files(str(tmp_path))
        assert result["count"] >= 1

    def test_no_test_files(self, tmp_path: Path):
        """No test files should return count=0."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("def main(): pass")
        (src_dir / "utils.py").write_text("def helper(): pass")

        result = detect_test_files(str(tmp_path))
        assert result["count"] == 0
        assert result["sample_files"] == []

    def test_excluded_dirs_skipped(self, tmp_path: Path):
        """Test files in node_modules, .git, etc. are skipped."""
        nm_dir = tmp_path / "node_modules" / "package" / "tests"
        nm_dir.mkdir(parents=True)
        (nm_dir / "test_lib.js").write_text("test('x', () => {})")

        result = detect_test_files(str(tmp_path))
        assert result["count"] == 0

    def test_sample_files_capped(self, tmp_path: Path):
        """sample_files is capped at 5."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        for i in range(10):
            (tests_dir / f"test_{i}.py").write_text("")

        result = detect_test_files(str(tmp_path))
        assert len(result["sample_files"]) <= 5
        assert result["count"] == 10

    def test_language_breakdown(self, tmp_path: Path):
        """Language breakdown reports correct language for each test file."""
        (tmp_path / "test_auth.py").write_text("")
        (tmp_path / "foo.test.ts").write_text("")
        (tmp_path / "handler_test.go").write_text("")

        result = detect_test_files(str(tmp_path))
        assert "python" in result["languages"]
        assert "typescript" in result["languages"]
        assert "go" in result["languages"]


# ═══════════════════════════════════════════════════════════════════════════════
# compute_test_coverage_signal tests
# ═══════════════════════════════════════════════════════════════════════════════


def _make_node(id: str, type: NodeType, file_path: str, name: str = "") -> GraphNode:
    return GraphNode(
        id=id, type=type, name=name or id.split("::")[-1],
        file_path=file_path, module="",
        qualified_name=id,
    )


def _make_edge(id: str, type: EdgeType, source: str, target: str,
               confidence: float, resolution: Resolution = Resolution.test_name_heuristic) -> GraphEdge:
    return GraphEdge(
        id=id, type=type, source=source, target=target,
        confidence=confidence,
        metadata=EdgeMetadata(resolution=resolution),
    )


class TestComputeTestCoverageSignal:
    """Structured coverage signal computation."""

    def test_no_test_files_no_edges(self):
        """Case A: No test files, no tested_by edges → unknown."""
        nodes = [
            _make_node("main.py::main", NodeType.function, "main.py"),
        ]
        edges: list[GraphEdge] = []

        signal = compute_test_coverage_signal(nodes, edges)
        assert signal["status"] == "unknown"
        assert signal["test_files_detected"] == 0
        assert signal["tested_by_edges"] == 0
        assert signal["test_files"] == 0  # backward compat
        assert signal["tested_symbols"] == 0  # backward compat

    def test_test_files_detected_but_no_edges(self, tmp_path: Path):
        """Case B: Test files on disk but no tested_by edges → incomplete."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_auth.py").write_text("def test_login(): pass")

        nodes = [
            _make_node("main.py::main", NodeType.function, "main.py"),
        ]
        edges: list[GraphEdge] = []

        signal = compute_test_coverage_signal(nodes, edges, str(tmp_path))
        assert signal["status"] == "incomplete"
        assert signal["test_files_detected"] >= 1
        assert signal["tested_by_edges"] == 0
        assert "detected" in signal["message"].lower()
        assert len(signal["warnings"]) >= 1

    def test_indexed_test_files_but_no_edges(self):
        """Indexed test nodes exist but no tested_by edges → incomplete."""
        nodes = [
            _make_node("main.py::main", NodeType.function, "main.py"),
            _make_node("tests/test_auth.py::test_login", NodeType.test, "tests/test_auth.py"),
        ]
        edges: list[GraphEdge] = []

        signal = compute_test_coverage_signal(nodes, edges)
        assert signal["status"] == "incomplete"
        assert signal["test_files_detected"] >= 1
        assert signal["tested_by_edges"] == 0
        assert len(signal["warnings"]) >= 1

    def test_low_confidence_edges(self):
        """Case C: tested_by edges exist but are low confidence → low_confidence."""
        nodes = [
            _make_node("main.py::main", NodeType.function, "main.py"),
            _make_node("main.py::helper", NodeType.function, "main.py"),
            _make_node("tests/test_auth.py::test_login", NodeType.test, "tests/test_auth.py"),
            _make_node("tests/test_auth.py::test_helper", NodeType.test, "tests/test_auth.py"),
        ]
        edges = [
            _make_edge("e1", EdgeType.tested_by,
                       "main.py::main", "tests/test_auth.py::test_login",
                       confidence=0.55, resolution=Resolution.test_file_heuristic),
            _make_edge("e2", EdgeType.tested_by,
                       "main.py::helper", "tests/test_auth.py::test_helper",
                       confidence=0.60, resolution=Resolution.test_name_heuristic),
        ]

        signal = compute_test_coverage_signal(nodes, edges)
        assert signal["status"] == "low_confidence"
        assert signal["tested_by_edges"] == 2
        assert signal["tested_symbols_high_confidence"] == 0
        assert signal["tested_symbols_low_confidence"] == 2

    def test_high_confidence_edges(self):
        """Case D: High confidence tested_by edges → ok."""
        nodes = [
            _make_node("main.py::login", NodeType.function, "main.py"),
            _make_node("main.py::logout", NodeType.function, "main.py"),
            _make_node("tests/test_auth.py::test_login", NodeType.test, "tests/test_auth.py"),
            _make_node("tests/test_auth.py::test_logout", NodeType.test, "tests/test_auth.py"),
        ]
        edges = [
            _make_edge("e1", EdgeType.tested_by,
                       "main.py::login", "tests/test_auth.py::test_login",
                       confidence=0.90, resolution=Resolution.direct_test_call),
            _make_edge("e2", EdgeType.tested_by,
                       "main.py::logout", "tests/test_auth.py::test_logout",
                       confidence=0.80, resolution=Resolution.test_import_match),
        ]

        signal = compute_test_coverage_signal(nodes, edges)
        assert signal["status"] == "ok"
        assert signal["tested_by_edges"] == 2
        assert signal["tested_symbols_high_confidence"] >= 1

    def test_mixed_confidence_edges_majority_high(self):
        """Mixed confidence, majority ≥ threshold → ok."""
        nodes = [
            _make_node("main.py::login", NodeType.function, "main.py"),
            _make_node("tests/test_auth.py::test_login", NodeType.test, "tests/test_auth.py"),
        ]
        edges = [
            _make_edge("e1", EdgeType.tested_by,
                       "main.py::login", "tests/test_auth.py::test_login",
                       confidence=0.90),
            _make_edge("e2", EdgeType.tested_by,
                       "main.py::login", "tests/test_auth.py::test_login",
                       confidence=0.90),
            _make_edge("e3", EdgeType.tested_by,
                       "main.py::login", "tests/test_auth.py::test_login",
                       confidence=0.50),
        ]

        signal = compute_test_coverage_signal(nodes, edges)
        # 2/3 >= 50% high → ok
        assert signal["status"] == "ok"

    def test_mixed_confidence_edges_minority_high(self):
        """Mixed confidence, minority high → low_confidence."""
        nodes = [
            _make_node("main.py::a", NodeType.function, "main.py"),
            _make_node("main.py::b", NodeType.function, "main.py"),
            _make_node("main.py::c", NodeType.function, "main.py"),
            _make_node("main.py::d", NodeType.function, "main.py"),
            _make_node("tests/t.py::test_a", NodeType.test, "tests/t.py"),
            _make_node("tests/t.py::test_b", NodeType.test, "tests/t.py"),
            _make_node("tests/t.py::test_c", NodeType.test, "tests/t.py"),
            _make_node("tests/t.py::test_d", NodeType.test, "tests/t.py"),
        ]
        edges = [
            _make_edge("e1", EdgeType.tested_by,
                       "main.py::a", "tests/t.py::test_a",
                       confidence=0.90),
            _make_edge("e2", EdgeType.tested_by,
                       "main.py::b", "tests/t.py::test_b",
                       confidence=0.50),
            _make_edge("e3", EdgeType.tested_by,
                       "main.py::c", "tests/t.py::test_c",
                       confidence=0.40),
            _make_edge("e4", EdgeType.tested_by,
                       "main.py::d", "tests/t.py::test_d",
                       confidence=0.35),
        ]

        signal = compute_test_coverage_signal(nodes, edges)
        # 1/4 < 50% high → low_confidence
        assert signal["status"] == "low_confidence"

    def test_backward_compat_fields(self):
        """Old test_files and tested_symbols are present as ints."""
        nodes = [
            _make_node("main.py::login", NodeType.function, "main.py"),
            _make_node("tests/test_auth.py::test_login", NodeType.test, "tests/test_auth.py"),
        ]
        edges = [
            _make_edge("e1", EdgeType.tested_by,
                       "main.py::login", "tests/test_auth.py::test_login",
                       confidence=0.90),
        ]

        signal = compute_test_coverage_signal(nodes, edges)
        assert "test_files" in signal
        assert "tested_symbols" in signal
        assert isinstance(signal["test_files"], int)
        assert isinstance(signal["tested_symbols"], int)
        assert signal["test_files"] >= 1
        assert signal["tested_symbols"] >= 1

    def test_message_never_says_no_tests_when_files_exist(self, tmp_path: Path):
        """When test files exist, message must not claim 'No test files were detected'."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_auth.py").write_text("def test_login(): pass")

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        signal = compute_test_coverage_signal(nodes, edges, str(tmp_path))
        msg = signal["message"].lower()
        # Must not say "No test files were detected" when test files exist
        assert "no test files were detected" not in msg
        # Should say files were detected
        assert "detected" in msg or "test files" in msg

    def test_message_mentions_limitations(self):
        """Message should guide agents to verify independently."""
        nodes = [
            _make_node("main.py::login", NodeType.function, "main.py"),
            _make_node("tests/test_auth.py::test_login", NodeType.test, "tests/test_auth.py"),
        ]
        edges: list[GraphEdge] = []  # no tested_by edges

        signal = compute_test_coverage_signal(nodes, edges)
        # Message should mention verification or limitations
        msg = signal["message"].lower()
        has_guidance = "verify" in msg or "cannot confidently" in msg or "codograph" in msg
        assert has_guidance or signal["status"] == "incomplete"

    def test_untested_symbols_estimate(self):
        """untested_symbols_estimate counts production symbols without tested_by."""
        nodes = [
            _make_node("main.py::login", NodeType.function, "main.py"),
            _make_node("main.py::logout", NodeType.function, "main.py"),
            _make_node("main.py::User", NodeType.class_, "main.py"),
            _make_node("tests/test_auth.py::test_login", NodeType.test, "tests/test_auth.py"),
        ]
        edges = [
            _make_edge("e1", EdgeType.tested_by,
                       "main.py::login", "tests/test_auth.py::test_login",
                       confidence=0.90),
        ]

        signal = compute_test_coverage_signal(nodes, edges)
        # 3 production nodes, 1 tested → 2 untested
        assert signal["untested_symbols_estimate"] == 2

    def test_missing_confidence_is_unknown(self):
        """Edges with exactly 0 confidence (effectively missing) go to unknown bucket."""
        nodes = [
            _make_node("main.py::login", NodeType.function, "main.py"),
            _make_node("tests/test_auth.py::test_login", NodeType.test, "tests/test_auth.py"),
        ]
        edges = [
            GraphEdge(
                id="e1", type=EdgeType.tested_by,
                source="main.py::login", target="tests/test_auth.py::test_login",
                confidence=0.0,  # effectively missing
            ),
        ]

        signal = compute_test_coverage_signal(nodes, edges)
        assert signal["tested_symbols_unknown_confidence"] == 1
        assert signal["tested_symbols_high_confidence"] == 0
        assert signal["tested_symbols_low_confidence"] == 0

    def test_multiple_test_file_patterns_detected(self, tmp_path: Path):
        """Mixed language test files are all detected."""
        (tmp_path / "test_py.py").write_text("")
        (tmp_path / "foo.test.ts").write_text("")
        (tmp_path / "foo_test.go").write_text("")
        (tmp_path / "FooTest.java").write_text("")

        result = detect_test_files(str(tmp_path))
        assert result["count"] >= 4
        langs = result["languages"]
        assert "python" in langs
        assert "typescript" in langs
        assert "go" in langs
        assert "java" in langs

    def test_warnings_not_empty_for_incomplete(self, tmp_path: Path):
        """Incomplete status must include warnings."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_auth.py").write_text("def test_login(): pass")

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        signal = compute_test_coverage_signal(nodes, edges, str(tmp_path))
        assert len(signal["warnings"]) > 0

    def test_status_is_unknown_for_empty_project(self):
        """Empty project with no test files → unknown."""
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        signal = compute_test_coverage_signal(nodes, edges)
        assert signal["status"] == "unknown"
        assert signal["confidence"] == "unknown"

    def test_test_file_detection_included_when_root_provided(self, tmp_path: Path):
        """When project_root is provided, test_file_detection details are included."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_auth.py").write_text("")

        signal = compute_test_coverage_signal([], [], str(tmp_path))
        assert "test_file_detection" in signal
        assert signal["test_file_detection"]["method"] == "filesystem_heuristic"
        assert signal["test_file_detection"]["count"] >= 1
        assert len(signal["test_file_detection"]["sample_files"]) >= 1

    def test_test_file_detection_absent_without_root(self):
        """When project_root is not provided, no filesystem detection."""
        signal = compute_test_coverage_signal([], [])
        assert "test_file_detection" not in signal

    def test_high_confidence_threshold_boundary(self):
        """Test exactly at the threshold boundary."""
        threshold = TESTED_BY_HIGH_CONFIDENCE_THRESHOLD
        nodes = [
            _make_node("main.py::f", NodeType.function, "main.py"),
            _make_node("tests/t.py::test_f", NodeType.test, "tests/t.py"),
        ]
        # At threshold → high
        edges_high = [
            _make_edge("e1", EdgeType.tested_by,
                       "main.py::f", "tests/t.py::test_f",
                       confidence=threshold),
        ]
        signal = compute_test_coverage_signal(nodes, edges_high)
        assert signal["tested_symbols_high_confidence"] == 1

        # Just below threshold → low
        edges_low = [
            _make_edge("e1", EdgeType.tested_by,
                       "main.py::f", "tests/t.py::test_f",
                       confidence=threshold - 0.01),
        ]
        signal = compute_test_coverage_signal(nodes, edges_low)
        assert signal["tested_symbols_low_confidence"] == 1
