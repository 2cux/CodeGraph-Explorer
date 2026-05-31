"""P2 Engineering reliability hardening tests.

Covers:
- Path compatibility: Chinese, spaces, Windows backslashes
- Symlink security: skip outside-root symlinks, reject source reads
- SQLite batch chunking: large inserts without SQL variable overflow
- Stale index detection: modified/added/deleted file detection
- Impact conservative defaults: no siblings, low-confidence separation
- Unified warnings: stable shape for all warning types
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

from codegraph.graph.models import (
    GraphNode, GraphEdge, EdgeType, NodeType, Resolution,
    Location, EdgeLocation, EdgeMetadata,
)
from codegraph.graph.store import GraphStore
from codegraph.graph.impact import analyze_impact, transitive_callers, transitive_callees
from codegraph.graph.warnings import (
    WARNING_TYPES, build_warning, build_stale_index_warning,
)
from codegraph.indexer.scanner import (
    scan_python_files, normalize_path, _is_safe_path, read_file_safe,
)
from codegraph.indexer.status import detect_status, StatusResult
from codegraph.indexer.graph_builder import build_index
from codegraph.storage.sqlite_store import SqliteStore
from codegraph.storage.sqlite_utils import chunked, safe_executemany, DEFAULT_CHUNK_SIZE

# ── Path to fixtures ────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PATH_COMPAT_DIR = FIXTURES_DIR / "path_compat"
SYMLINK_DIR = FIXTURES_DIR / "symlink_test"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Path compatibility: Chinese, spaces, Windows backslashes
# ═══════════════════════════════════════════════════════════════════════════════


class TestPathCompatCJKAndSpaces:
    """Indexing and querying projects with Chinese and space-containing paths."""

    def test_scan_finds_chinese_path_files(self):
        """Scanner discovers .py files in directories with Chinese names and spaces."""
        root = PATH_COMPAT_DIR
        files = scan_python_files(root)
        rel_paths = [normalize_path(f.relative_to(root)) for f in files]
        assert any("认证 模块.py" in r for r in rel_paths), \
            f"Should find Chinese-named file, got: {rel_paths}"

    def test_index_chinese_path_project(self):
        """Building the index on a Chinese-path project succeeds."""
        root = PATH_COMPAT_DIR
        nodes, edges = build_index(root)
        assert len(nodes) > 0, "Should extract nodes from Chinese-path files"

        # Find the login function
        login_nodes = [n for n in nodes if n.name == "login"]
        assert len(login_nodes) >= 1, "login function should be found"

        login = login_nodes[0]
        # The file_path should use POSIX slashes (normalized)
        assert "\\" not in login.file_path, \
            f"file_path should use POSIX slashes: {login.file_path}"
        assert "认证 模块" in login.file_path, \
            f"file_path should contain the Chinese filename: {login.file_path}"

    def test_search_symbols_finds_login_in_chinese_path(self):
        """Searching by name works for symbols in Chinese paths."""
        root = PATH_COMPAT_DIR
        nodes, edges = build_index(root)
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        results = store.search_nodes("login")
        login_ids = [r.id for r in results if r.name == "login"]
        assert len(login_ids) >= 1, f"search_nodes should find login, got: {login_ids}"

    def test_get_symbol_reads_chinese_path_symbol(self):
        """get_symbol can retrieve a symbol from a Chinese-named file."""
        root = PATH_COMPAT_DIR
        nodes, edges = build_index(root)
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        login_nodes = [n for n in nodes if n.name == "login"]
        assert len(login_nodes) >= 1
        login = login_nodes[0]

        retrieved = store.get_node(login.id)
        assert retrieved is not None
        assert retrieved.name == "login"
        assert retrieved.file_path == login.file_path

    def test_graph_json_paths_not_garbled(self):
        """Paths in graph nodes use correct encoding, not garbled."""
        root = PATH_COMPAT_DIR
        nodes, edges = build_index(root)
        for node in nodes:
            if node.file_path:
                # Should be valid readable text, not mojibake
                assert "\\ufffd" not in node.file_path  # replacement character
                assert "\\x" not in node.file_path  # raw hex escapes
                assert "Ã" not in node.file_path  # UTF-8 misinterpreted as latin1

    def test_node_id_contains_normalized_path(self):
        """Node IDs use POSIX forward-slash paths."""
        root = PATH_COMPAT_DIR
        nodes, edges = build_index(root)
        for node in nodes:
            if "::" in node.id:
                file_part = node.id.split("::")[0]
                assert "\\" not in file_part, \
                    f"Node ID should not contain backslashes: {node.id}"


class TestWindowsPathNormalization:
    """Windows backslash paths are normalized to POSIX forward slashes."""

    def test_normalize_backslashes(self):
        assert normalize_path("src\\app\\api\\auth.py") == "src/app/api/auth.py"

    def test_normalize_mixed_slashes(self):
        assert normalize_path("src\\app/api\\auth.py") == "src/app/api/auth.py"

    def test_normalize_already_posix(self):
        assert normalize_path("src/app/api/auth.py") == "src/app/api/auth.py"

    def test_normalize_pathlib_windows(self):
        p = Path("src\\app\\api\\auth.py")
        assert normalize_path(p) == "src/app/api/auth.py"

    def test_normalize_chinese_with_backslashes(self):
        raw = "项目 示例\\app\\api\\认证 模块.py"
        expected = "项目 示例/app/api/认证 模块.py"
        assert normalize_path(raw) == expected

    def test_build_index_uses_normalized_paths(self):
        """All generated node IDs use POSIX slashes regardless of input."""
        root = PATH_COMPAT_DIR
        nodes, edges = build_index(root)
        for node in nodes:
            assert "\\" not in node.file_path, \
                f"file_path has backslash: {node.file_path}"
            assert "\\" not in node.id, \
                f"id has backslash: {node.id}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Symlink security
# ═══════════════════════════════════════════════════════════════════════════════


class TestSymlinkOutsideRootSkipped:
    """Symlinks pointing outside repo root are skipped during scanning."""

    def test_symlink_outside_root_skipped_in_scan(self):
        """Scanner skips files whose realpath is outside repo root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            app_dir = repo_root / "app"
            app_dir.mkdir()

            # Create a legitimate file
            (app_dir / "main.py").write_text("def foo(): pass", encoding="utf-8")

            # Create a file outside the repo
            outside_dir = Path(tmpdir) / "outside"
            outside_dir.mkdir()
            secret_file = outside_dir / "secret.py"
            secret_file.write_text("SECRET = 'outside'", encoding="utf-8")

            # Create a symlink inside the repo pointing outside
            symlink_path = app_dir / "link_to_secret.py"
            try:
                os.symlink(str(secret_file.resolve()), str(symlink_path))
            except OSError:
                pytest.skip("Symlink creation requires developer mode or admin on Windows")

            warnings: list[dict] = []
            files = scan_python_files(repo_root, collect_warnings=warnings)

            rel_files = [normalize_path(f.relative_to(repo_root)) for f in files]
            assert "app/main.py" in rel_files
            assert "app/link_to_secret.py" not in rel_files, \
                "Symlink to outside file should be excluded"

            # Check that warning was emitted
            symlink_warnings = [w for w in warnings if w["type"] == "symlink_outside_root"]
            assert len(symlink_warnings) >= 1, \
                f"Should emit symlink_outside_root warning, got: {warnings}"

    def test_is_safe_path_rejects_outside_symlink(self):
        """_is_safe_path returns False for paths pointing outside root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            (repo_root / "legit.py").write_text("x=1", encoding="utf-8")

            outside = Path(tmpdir) / "outside"
            outside.mkdir()
            (outside / "secret.py").write_text("SECRET=1", encoding="utf-8")

            link = repo_root / "escape_link.py"
            try:
                os.symlink(str(outside.resolve() / "secret.py"), str(link))
            except OSError:
                pytest.skip("Symlink creation requires developer mode or admin on Windows")

            is_safe, msg = _is_safe_path(link, repo_root)
            assert not is_safe, f"Symlink outside root should be unsafe, got: {msg}"
            assert msg is not None

    def test_is_safe_path_accepts_internal_file(self):
        """_is_safe_path returns True for normal internal files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            internal = repo_root / "app" / "main.py"
            internal.parent.mkdir()
            internal.write_text("def foo(): pass", encoding="utf-8")

            is_safe, msg = _is_safe_path(internal, repo_root)
            assert is_safe, f"Internal file should be safe, got: {msg}"

    def test_is_safe_path_accepts_internal_symlink(self):
        """_is_safe_path returns True for symlinks that stay inside root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            app_dir = repo_root / "app"
            app_dir.mkdir()
            (app_dir / "real.py").write_text("def foo(): pass", encoding="utf-8")

            link = app_dir / "link.py"
            try:
                os.symlink(str((app_dir / "real.py").resolve()), str(link))
            except OSError:
                pytest.skip("Symlink creation requires developer mode or admin on Windows")

            is_safe, _ = _is_safe_path(link, repo_root)
            assert is_safe, "Internal symlink should be safe"

    def test_read_file_safe_rejects_outside_symlink(self):
        """read_file_safe returns None for paths outside root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()

            outside = Path(tmpdir) / "outside"
            outside.mkdir()
            (outside / "secret.py").write_text("SECRET=1", encoding="utf-8")

            link = repo_root / "escape.py"
            try:
                os.symlink(str(outside.resolve() / "secret.py"), str(link))
            except OSError:
                pytest.skip("Symlink creation requires developer mode or admin on Windows")

            content = read_file_safe(link, repo_root)
            assert content is None, "read_file_safe should return None for outside symlink"

    def test_read_file_safe_reads_internal_file(self):
        """read_file_safe returns content for internal files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            f = repo_root / "main.py"
            f.write_text("answer = 42", encoding="utf-8")

            content = read_file_safe(f, repo_root)
            assert content == "answer = 42"


class TestSourceReadRejectsSymlinkEscape:
    """MCP server _read_source_snippet rejects symlink escapes."""

    def test_source_read_rejects_outside_symlink(self):
        """The source snippet reader validates realpath before reading."""
        # We test _is_safe_path directly as a proxy for the MCP check
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            outside = Path(tmpdir) / "outside"
            outside.mkdir()
            (outside / "secret.py").write_text("SECRET=1", encoding="utf-8")

            link = repo_root / "escape.py"
            try:
                os.symlink(str(outside.resolve() / "secret.py"), str(link))
            except OSError:
                pytest.skip("Symlink creation requires developer mode or admin on Windows")

            # When the MCP tries to resolve this path with realpath,
            # it should be rejected
            full_path = repo_root / "escape.py"
            is_safe, _ = _is_safe_path(full_path, repo_root)
            assert not is_safe, \
                "Symlink to outside should be rejected before reading source"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SQLite batch chunking
# ═══════════════════════════════════════════════════════════════════════════════


class TestSqliteSafeChunkingLargeInsert:
    """Large batch inserts are chunked to avoid SQLite parameter limits."""

    @staticmethod
    def _make_node_dict(node_id: str) -> dict:
        return {
            "id": node_id,
            "type": "function",
            "name": f"func_{node_id}",
            "qualified_name": f"module.func_{node_id}",
            "display_name": f"func_{node_id}",
            "file_path": "app/module.py",
            "module": "app.module",
            "language": "python",
            "location": None,
            "signature": None,
            "docstring": None,
            "code_preview": None,
            "visibility": "public",
            "tags": [],
            "metadata": {},
        }

    @staticmethod
    def _make_edge_dict(edge_id: str, source: str, target: str) -> dict:
        return {
            "id": edge_id,
            "type": "calls",
            "source": source,
            "target": target,
            "confidence": 0.9,
            "source_location": None,
            "metadata": None,
        }

    def test_chunked_yields_correct_sizes(self):
        data = list(range(100))
        chunks = list(chunked(data, 30))
        assert len(chunks) == 4
        assert chunks[0] == list(range(30))
        assert chunks[1] == list(range(30, 60))
        assert chunks[2] == list(range(60, 90))
        assert chunks[3] == list(range(90, 100))

    def test_chunked_empty(self):
        assert list(chunked([], 10)) == []

    def test_chunked_single(self):
        assert list(chunked([1], 10)) == [[1]]

    def test_safe_executemany_chunks_large_batch(self):
        """Writing 2500 nodes in one call doesn't fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            store = SqliteStore(db_path)
            store.initialize()

            nodes = [self._make_node_dict(f"node_{i:04d}") for i in range(2500)]
            store.save_nodes(nodes)

            assert store.node_count() == 2500
            store.close()

    def test_safe_executemany_chunks_large_edge_batch(self):
        """Writing 6000 edges in one call doesn't fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            store = SqliteStore(db_path)
            store.initialize()

            # Create nodes first
            nodes = [self._make_node_dict(f"node_{i:04d}") for i in range(2000)]
            store.save_nodes(nodes)

            # Now create many edges referencing those nodes
            import random
            random.seed(42)
            edges = []
            for i in range(6000):
                src = f"node_{random.randint(0, 1999):04d}"
                tgt = f"node_{random.randint(0, 1999):04d}"
                edges.append(self._make_edge_dict(f"edge_{i:04d}", src, tgt))
            store.save_edges(edges)

            assert store.edge_count() == 6000
            store.close()

    def test_write_count_matches_query_count(self):
        """After large insert, query counts are correct."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            store = SqliteStore(db_path)
            store.initialize()

            nodes = [self._make_node_dict(f"n{i:04d}") for i in range(1200)]
            store.save_nodes(nodes)
            assert store.node_count() == 1200

            all_nodes = store.load_all_nodes()
            assert len(all_nodes) == 1200

            # Query with filters still works
            results = store.query_nodes({"limit": 100})
            assert len(results) == 100
            store.close()

    def test_chunking_does_not_silently_truncate(self):
        """Verify no data loss from chunking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            store = SqliteStore(db_path)
            store.initialize()

            nodes = [self._make_node_dict(f"sym_{i:04d}") for i in range(777)]
            store.save_nodes(nodes)
            assert store.node_count() == 777

            # Spot-check specific entries
            first = store.get_node("sym_0000")
            assert first is not None
            assert first["name"] == "func_sym_0000"

            last = store.get_node("sym_0776")
            assert last is not None
            assert last["name"] == "func_sym_0776"

            mid = store.get_node("sym_0388")
            assert mid is not None
            store.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Stale index detection
# ═══════════════════════════════════════════════════════════════════════════════


class TestRepoStatusDetectsModifiedFile:
    """repo_status detects modified files."""

    def test_status_fresh_after_index(self):
        """After indexing, status is fresh."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "main.py").write_text("def foo(): pass\n", encoding="utf-8")

            from codegraph.graph.models import IndexMetadata, FileEntry
            from codegraph.indexer.scanner import compute_fingerprint

            files = list(scan_python_files(root))
            metadata = IndexMetadata(
                schema_version="1.0.0",
                root_path=str(root),
                indexed_at="2025-01-01T00:00:00",
                file_count=len(files),
                symbol_count=0,
                edge_count=0,
                files=[FileEntry(
                    path=normalize_path(f.relative_to(root)),
                    fingerprint=compute_fingerprint(f),
                    indexed_at="2025-01-01T00:00:00",
                ) for f in files],
            )

            result = detect_status(root, metadata)
            assert result.status == "fresh", f"Expected fresh, got {result.status}"

    def test_status_stale_after_modification(self):
        """After modifying a file, status becomes stale."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            py_file = root / "main.py"
            py_file.write_text("def foo(): pass\n", encoding="utf-8")

            from codegraph.graph.models import IndexMetadata, FileEntry
            from codegraph.indexer.scanner import compute_fingerprint

            files = list(scan_python_files(root))
            # Store the ORIGINAL fingerprint
            metadata = IndexMetadata(
                schema_version="1.0.0",
                root_path=str(root),
                indexed_at="2025-01-01T00:00:00",
                file_count=len(files),
                symbol_count=0,
                edge_count=0,
                files=[FileEntry(
                    path=normalize_path(f.relative_to(root)),
                    fingerprint=compute_fingerprint(f),
                    indexed_at="2025-01-01T00:00:00",
                ) for f in files],
            )

            # Now modify the file
            py_file.write_text("def foo(): return 42\n", encoding="utf-8")

            result = detect_status(root, metadata)
            assert result.status == "stale", f"Expected stale after modification, got {result.status}"
            assert len(result.changed_files) >= 1
            assert "main.py" in result.changed_files

    def test_status_stale_after_added_file(self):
        """After adding a new .py file, status becomes stale."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "main.py").write_text("def foo(): pass\n", encoding="utf-8")

            from codegraph.graph.models import IndexMetadata, FileEntry
            from codegraph.indexer.scanner import compute_fingerprint

            files_before = list(scan_python_files(root))
            metadata = IndexMetadata(
                schema_version="1.0.0",
                root_path=str(root),
                indexed_at="2025-01-01T00:00:00",
                file_count=len(files_before),
                symbol_count=0,
                edge_count=0,
                files=[FileEntry(
                    path=normalize_path(f.relative_to(root)),
                    fingerprint=compute_fingerprint(f),
                    indexed_at="2025-01-01T00:00:00",
                ) for f in files_before],
            )

            # Add a new file
            (root / "new_module.py").write_text("def bar(): pass\n", encoding="utf-8")

            result = detect_status(root, metadata)
            assert result.status == "stale", f"Expected stale after adding file, got {result.status}"
            assert len(result.added_files) >= 1
            assert "new_module.py" in result.added_files

    def test_status_stale_after_deleted_file(self):
        """After deleting an indexed file, status becomes stale."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            py_file = root / "main.py"
            py_file.write_text("def foo(): pass\n", encoding="utf-8")
            extra_file = root / "extra.py"
            extra_file.write_text("x = 1\n", encoding="utf-8")

            from codegraph.graph.models import IndexMetadata, FileEntry
            from codegraph.indexer.scanner import compute_fingerprint

            files_before = list(scan_python_files(root))
            metadata = IndexMetadata(
                schema_version="1.0.0",
                root_path=str(root),
                indexed_at="2025-01-01T00:00:00",
                file_count=len(files_before),
                symbol_count=0,
                edge_count=0,
                files=[FileEntry(
                    path=normalize_path(f.relative_to(root)),
                    fingerprint=compute_fingerprint(f),
                    indexed_at="2025-01-01T00:00:00",
                ) for f in files_before],
            )

            # Delete extra.py
            extra_file.unlink()

            result = detect_status(root, metadata)
            assert result.status == "stale", f"Expected stale after deletion, got {result.status}"
            assert len(result.deleted_files) >= 1
            assert "extra.py" in result.deleted_files

    def test_status_missing_when_no_metadata(self):
        """Status is 'missing' when metadata is None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = detect_status(root, None)
            assert result.status == "missing"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Impact conservative defaults
# ═══════════════════════════════════════════════════════════════════════════════


class TestImpactConservativeExcludesSiblings:
    """Conservative impact does NOT include same-module siblings without calls."""

    def _build_store_with_siblings(self):
        """Build a store with two functions in the same module, only one calling the other."""
        store = GraphStore()

        # Module with two functions: caller directly calls helper, but sibling doesn't
        store.add_nodes([
            GraphNode(
                id="app/module.py",
                type=NodeType.file,
                name="module.py",
                file_path="app/module.py",
                module="app.module",
            ),
            GraphNode(
                id="app/module.py::caller",
                type=NodeType.function,
                name="caller",
                file_path="app/module.py",
                module="app.module",
                qualified_name="app.module.caller",
                location=Location(line_start=1, line_end=3),
            ),
            GraphNode(
                id="app/module.py::helper",
                type=NodeType.function,
                name="helper",
                file_path="app/module.py",
                module="app.module",
                qualified_name="app.module.helper",
                location=Location(line_start=5, line_end=7),
            ),
            GraphNode(
                id="app/module.py::sibling",
                type=NodeType.function,
                name="sibling",
                file_path="app/module.py",
                module="app.module",
                qualified_name="app.module.sibling",
                location=Location(line_start=9, line_end=11),
            ),
        ])

        # caller -> helper (direct call, high confidence)
        store.add_edges([
            GraphEdge(
                id="edge_001",
                type=EdgeType.calls,
                source="app/module.py::caller",
                target="app/module.py::helper",
                confidence=0.95,
                metadata=EdgeMetadata(
                    resolution=Resolution.same_file_exact,
                    reason="caller calls helper",
                ),
            ),
        ])

        return store

    def test_sibling_not_in_confirmed_impact(self):
        """A same-module sibling without a call edge is NOT in confirmed_impact."""
        store = self._build_store_with_siblings()

        # Analyze impact of `caller`
        result = analyze_impact(store, "app/module.py::caller", depth=1, min_confidence=0.6)

        confirmed_ids = {s["symbol_id"] for s in result["confirmed_impact"]["symbols"]}
        # caller itself should be in confirmed
        assert "app/module.py::caller" in confirmed_ids
        # helper should be in confirmed (direct callee, high confidence)
        assert "app/module.py::helper" in confirmed_ids
        # sibling should NOT be in confirmed (no call relationship)
        assert "app/module.py::sibling" not in confirmed_ids, \
            "Same-module sibling without call edge should NOT be in confirmed_impact"

    def test_sibling_not_in_possible_when_include_possible_false(self):
        """Possible impact is empty when include_possible is not set."""
        store = self._build_store_with_siblings()
        result = analyze_impact(store, "app/module.py::caller", depth=1, min_confidence=0.6)
        possible_ids = {s["symbol_id"] for s in result["possible_impact"]["symbols"]}
        assert "app/module.py::sibling" not in possible_ids


class TestLowConfidenceNotConfirmedImpact:
    """Low-confidence edges do NOT enter confirmed_impact."""

    def _build_store_with_low_confidence_edge(self):
        store = GraphStore()
        store.add_nodes([
            GraphNode(
                id="app/main.py",
                type=NodeType.file,
                name="main.py",
                file_path="app/main.py",
                module="app.main",
            ),
            GraphNode(
                id="app/main.py::caller",
                type=NodeType.function,
                name="caller",
                file_path="app/main.py",
                module="app.main",
                qualified_name="app.main.caller",
                location=Location(line_start=1, line_end=3),
            ),
            GraphNode(
                id="app/main.py::target",
                type=NodeType.function,
                name="target",
                file_path="app/main.py",
                module="app.main",
                qualified_name="app.main.target",
                location=Location(line_start=5, line_end=7),
            ),
            GraphNode(
                id="app/utils.py::helper",
                type=NodeType.function,
                name="helper",
                file_path="app/utils.py",
                module="app.utils",
                qualified_name="app.utils.helper",
                location=Location(line_start=1, line_end=3),
            ),
        ])

        # High confidence edge: caller -> target
        # Low confidence edge: caller -> helper
        store.add_edges([
            GraphEdge(
                id="edge_hc",
                type=EdgeType.calls,
                source="app/main.py::caller",
                target="app/main.py::target",
                confidence=0.95,
                metadata=EdgeMetadata(
                    resolution=Resolution.same_file_exact,
                    reason="high confidence call",
                ),
            ),
            GraphEdge(
                id="edge_lc",
                type=EdgeType.calls,
                source="app/main.py::caller",
                target="app/utils.py::helper",
                confidence=0.35,
                metadata=EdgeMetadata(
                    resolution=Resolution.attribute_guess,
                    reason="low confidence guess",
                ),
            ),
        ])

        return store

    def test_low_confidence_edge_not_in_confirmed(self):
        """Edge with confidence < 0.6 does not enter confirmed_impact."""
        store = self._build_store_with_low_confidence_edge()
        result = analyze_impact(store, "app/main.py::caller", depth=1, min_confidence=0.6)

        confirmed_ids = {s["symbol_id"] for s in result["confirmed_impact"]["symbols"]}
        assert "app/main.py::target" in confirmed_ids, "High-confidence callee should be in confirmed"
        assert "app/utils.py::helper" not in confirmed_ids, \
            "Low-confidence callee should NOT be in confirmed_impact"

    def test_low_confidence_edge_in_possible(self):
        """Edge with confidence < 0.6 enters possible_impact."""
        store = self._build_store_with_low_confidence_edge()
        result = analyze_impact(store, "app/main.py::caller", depth=1, min_confidence=0.6)

        possible_ids = {s["symbol_id"] for s in result["possible_impact"]["symbols"]}
        assert "app/utils.py::helper" in possible_ids, \
            "Low-confidence callee should be in possible_impact"

    def test_direct_caller_in_confirmed(self):
        """A direct caller with high confidence IS in confirmed_impact."""
        store = self._build_store_with_low_confidence_edge()
        result = analyze_impact(store, "app/main.py::target", depth=1, min_confidence=0.6)

        confirmed_ids = {s["symbol_id"] for s in result["confirmed_impact"]["symbols"]}
        assert "app/main.py::caller" in confirmed_ids, "Direct caller should be in confirmed"

    def test_tested_by_in_related_tests(self):
        """tested_by edges appear in related_tests, not confirmed_impact."""
        store = GraphStore()
        store.add_nodes([
            GraphNode(
                id="app/module.py::func",
                type=NodeType.function,
                name="func",
                file_path="app/module.py",
                module="app.module",
                qualified_name="app.module.func",
            ),
            GraphNode(
                id="tests/test_module.py::test_func",
                type=NodeType.test,
                name="test_func",
                file_path="tests/test_module.py",
                module="tests.test_module",
                qualified_name="tests.test_module.test_func",
            ),
        ])
        store.add_edges([
            GraphEdge(
                id="edge_001",
                type=EdgeType.tested_by,
                source="app/module.py::func",
                target="tests/test_module.py::test_func",
                confidence=0.9,
                metadata=EdgeMetadata(
                    resolution=Resolution.direct_test_call,
                    reason="test covers func",
                ),
            ),
        ])

        result = analyze_impact(store, "app/module.py::func", depth=1, min_confidence=0.6)
        test_ids = {t["symbol_id"] for t in result["related_tests"]}
        assert "tests/test_module.py::test_func" in test_ids, "Test should be in related_tests"


class TestImpactConfirmedPossibleSeparation:
    """confirmed_impact and possible_impact are always disjoint."""

    def test_confirmed_and_possible_disjoint(self):
        """No symbol appears in both confirmed and possible."""
        store = GraphStore()
        store.add_nodes([
            GraphNode(id="app/a.py::f1", type=NodeType.function, name="f1",
                      file_path="app/a.py", module="app.a", qualified_name="app.a.f1"),
            GraphNode(id="app/a.py::f2", type=NodeType.function, name="f2",
                      file_path="app/a.py", module="app.a", qualified_name="app.a.f2"),
        ])
        store.add_edges([
            GraphEdge(id="e1", type=EdgeType.calls, source="app/a.py::f1",
                      target="app/a.py::f2", confidence=0.95,
                      metadata=EdgeMetadata(resolution=Resolution.same_file_exact)),
        ])

        result = analyze_impact(store, "app/a.py::f1", depth=1, min_confidence=0.6)
        confirmed = {s["symbol_id"] for s in result["confirmed_impact"]["symbols"]}
        possible = {s["symbol_id"] for s in result["possible_impact"]["symbols"]}
        assert confirmed.isdisjoint(possible), \
            f"confirmed and possible must be disjoint, overlapping: {confirmed & possible}"

    def test_external_not_in_confirmed(self):
        """External/unresolved symbols never appear in confirmed_impact."""
        store = GraphStore()
        store.add_nodes([
            GraphNode(id="app/main.py::main", type=NodeType.function, name="main",
                      file_path="app/main.py", module="app.main", qualified_name="app.main.main"),
        ])
        store.add_edges([
            GraphEdge(id="e1", type=EdgeType.calls, source="app/main.py::main",
                      target="external:os.path.join", confidence=0.3,
                      metadata=EdgeMetadata(resolution=Resolution.external_symbol)),
        ])

        result = analyze_impact(store, "app/main.py::main", depth=1, min_confidence=0.6)
        confirmed_ids = {s["symbol_id"] for s in result["confirmed_impact"]["symbols"]}
        assert "external:os.path.join" not in confirmed_ids
        external_ids = {s["symbol_id"] for s in result["external_or_unresolved"]}
        assert "external:os.path.join" in external_ids


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Unified warnings
# ═══════════════════════════════════════════════════════════════════════════════


class TestWarningsHaveStableShape:
    """All warnings use the unified structured format."""

    REQUIRED_KEYS = {"type", "severity", "message", "reason_code"}

    def test_all_registered_warning_types_have_required_fields(self):
        """Every entry in WARNING_TYPES defines type, severity, description."""
        for wtype, template in WARNING_TYPES.items():
            assert "type" in template, f"{wtype} missing 'type'"
            assert "severity" in template, f"{wtype} missing 'severity'"
            assert template["severity"] in ("warning", "info"), \
                f"{wtype} has invalid severity: {template['severity']}"
            assert "description" in template, f"{wtype} missing 'description'"

    def test_build_warning_produces_stable_shape(self):
        """build_warning returns a dict with required keys."""
        w = build_warning("stale_index", message="Test stale", reason_code="stale")
        for key in self.REQUIRED_KEYS:
            assert key in w, f"Warning missing required key: {key}"

    def test_build_warning_merges_evidence(self):
        """Evidence dict is merged into the warning."""
        w = build_warning(
            "stale_index",
            message="Index stale",
            evidence={"changed_files": ["a.py"], "added_files": ["b.py"]},
            reason_code="stale_index",
        )
        assert w["changed_files"] == ["a.py"]
        assert w["added_files"] == ["b.py"]

    def test_build_stale_index_warning_has_evidence(self):
        """build_stale_index_warning includes file change evidence."""
        w = build_stale_index_warning(
            changed_files=["mod.py"],
            added_files=["new.py"],
            deleted_files=["gone.py"],
        )
        assert w["type"] == "stale_index"
        assert w["severity"] == "warning"
        assert w["changed_files"] == ["mod.py"]
        assert w["added_files"] == ["new.py"]
        assert w["deleted_files"] == ["gone.py"]
        assert "stale" in w["message"].lower()

    def test_build_stale_index_warning_defaults(self):
        """build_stale_index_warning works with empty args."""
        w = build_stale_index_warning()
        assert w["type"] == "stale_index"
        assert w["severity"] == "warning"
        # No file lists when empty (keys absent, not empty lists)

    def test_all_required_warning_types_exist(self):
        """All warning types specified in the PRD exist."""
        required_types = [
            "stale_index",
            "symlink_outside_root",
            "path_outside_root",
            "skipped_file",
            "low_confidence_edge",
            "unresolved_call",
            "external_symbol",
            "sqlite_chunking_applied",
            "fuzzy_match",
        ]
        for wt in required_types:
            assert wt in WARNING_TYPES, f"Missing required warning type: {wt}"

    def test_build_warning_unknown_type_defaults(self):
        """build_warning with unknown type still produces valid shape."""
        w = build_warning("nonexistent_type", message="Test")
        assert w["type"] == "nonexistent_type"
        assert w["severity"] == "info"  # default
        assert w["message"] == "Test"
        assert w["reason_code"] == "nonexistent_type"
