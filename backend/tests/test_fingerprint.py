"""Tests for fingerprint + change classification system."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from codegraph.indexer.fingerprint import (
    ChangeClassifier,
    ChangeType,
    FileFingerprint,
    FingerprintStore,
    compute_file_hashes,
    compute_fingerprints,
    stat_prefilter,
)
from codegraph.indexer.status import (
    StatusResult,
    detect_status_with_classification,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "fingerprint_cases"


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _path(name: str) -> Path:
    return FIXTURES_DIR / name


# ── Test FileFingerprint ──────────────────────────────────────────────────


class TestFileFingerprint:
    """Tests for the FileFingerprint Pydantic model."""

    def test_model_create(self):
        fp = FileFingerprint(
            file_path="test/file.py",
            mtime=123456.0,
            size=100,
            sha256="abc123",
            structural_hash="struct123",
            symbols_hash="sym123",
            imports_hash="imp123",
            calls_hash="call123",
        )
        assert fp.file_path == "test/file.py"
        assert fp.mtime == 123456.0
        assert fp.size == 100

    def test_model_serialization(self):
        fp = FileFingerprint(
            file_path="test/file.py",
            mtime=123456.0,
            size=100,
            sha256="abc",
            structural_hash="def",
            symbols_hash="ghi",
            imports_hash="jkl",
            calls_hash="mno",
        )
        data = fp.model_dump()
        assert data["file_path"] == "test/file.py"
        assert data["mtime"] == 123456.0
        assert data["sha256"] == "abc"

    def test_model_deserialization(self):
        data = {
            "file_path": "test/file.py",
            "mtime": 123456.0,
            "size": 100,
            "sha256": "abc",
            "structural_hash": "def",
            "symbols_hash": "ghi",
            "imports_hash": "jkl",
            "calls_hash": "mno",
        }
        fp = FileFingerprint.model_validate(data)
        assert fp.file_path == "test/file.py"
        assert fp.structural_hash == "def"


# ── Test FingerprintStore ─────────────────────────────────────────────────


class TestFingerprintStore:
    """Tests for FingerprintStore read/write operations."""

    def test_save_and_load(self, tmp_path: Path):
        store = FingerprintStore(tmp_path)
        fp = FileFingerprint(
            file_path="a.py", mtime=1.0, size=10,
            sha256="a", structural_hash="b", symbols_hash="c",
            imports_hash="d", calls_hash="e",
        )
        store.save({"a.py": fp})
        assert store.count() == 1
        loaded = store.load()
        assert "a.py" in loaded
        assert loaded["a.py"].sha256 == "a"

    def test_get(self, tmp_path: Path):
        store = FingerprintStore(tmp_path)
        fp = FileFingerprint(
            file_path="a.py", mtime=1.0, size=10,
            sha256="x", structural_hash="y", symbols_hash="z",
            imports_hash="w", calls_hash="v",
        )
        store.save({"a.py": fp})
        found = store.get("a.py")
        assert found is not None
        assert found.sha256 == "x"
        assert store.get("nonexistent.py") is None

    def test_update(self, tmp_path: Path):
        store = FingerprintStore(tmp_path)
        fp1 = FileFingerprint(
            file_path="a.py", mtime=1.0, size=10,
            sha256="old", structural_hash="old", symbols_hash="old",
            imports_hash="old", calls_hash="old",
        )
        store.save({"a.py": fp1})
        fp2 = FileFingerprint(
            file_path="a.py", mtime=2.0, size=20,
            sha256="new", structural_hash="new", symbols_hash="new",
            imports_hash="new", calls_hash="new",
        )
        store.update("a.py", fp2)
        loaded = store.load()
        assert loaded["a.py"].sha256 == "new"
        assert loaded["a.py"].mtime == 2.0

        # Update non-existent file adds it
        fp3 = FileFingerprint(
            file_path="b.py", mtime=3.0, size=30,
            sha256="b", structural_hash="b", symbols_hash="b",
            imports_hash="b", calls_hash="b",
        )
        store.update("b.py", fp3)
        assert store.count() == 2

    def test_remove(self, tmp_path: Path):
        store = FingerprintStore(tmp_path)
        fp = FileFingerprint(
            file_path="a.py", mtime=1.0, size=10,
            sha256="a", structural_hash="b", symbols_hash="c",
            imports_hash="d", calls_hash="e",
        )
        store.save({"a.py": fp, "b.py": fp})
        store.remove("a.py")
        assert store.count() == 1
        assert store.get("a.py") is None
        assert store.get("b.py") is not None

    def test_remove_many(self, tmp_path: Path):
        store = FingerprintStore(tmp_path)
        fp = FileFingerprint(
            file_path="a.py", mtime=1.0, size=10,
            sha256="a", structural_hash="b", symbols_hash="c",
            imports_hash="d", calls_hash="e",
        )
        store.save({"a.py": fp, "b.py": fp, "c.py": fp})
        store.remove_many({"a.py", "b.py"})
        assert store.count() == 1
        assert store.get("c.py") is not None

    def test_count(self, tmp_path: Path):
        store = FingerprintStore(tmp_path)
        assert store.count() == 0
        fp = FileFingerprint(
            file_path="a.py", mtime=1.0, size=10,
            sha256="a", structural_hash="b", symbols_hash="c",
            imports_hash="d", calls_hash="e",
        )
        store.save({"a.py": fp, "b.py": fp})
        assert store.count() == 2

    def test_empty_load(self, tmp_path: Path):
        store = FingerprintStore(tmp_path)
        loaded = store.load()
        assert loaded == {}

    def test_corrupt_file_returns_empty(self, tmp_path: Path):
        fp_path = tmp_path / "fingerprints.json"
        fp_path.write_text("not valid json {{{", encoding="utf-8")
        store = FingerprintStore(tmp_path)
        loaded = store.load()
        assert loaded == {}

    def test_atomic_write(self, tmp_path: Path):
        store = FingerprintStore(tmp_path)
        fp = FileFingerprint(
            file_path="a.py", mtime=1.0, size=10,
            sha256="a", structural_hash="b", symbols_hash="c",
            imports_hash="d", calls_hash="e",
        )
        store.save({"a.py": fp})
        assert (tmp_path / "fingerprints.json").exists()
        # tmp file should not remain
        assert not (tmp_path / "fingerprints.json.tmp").exists()


# ── Test ChangeClassifier ─────────────────────────────────────────────────


class TestChangeClassifier:
    """Tests for ChangeClassifier.classify()."""

    def _make_fp(self, sha256: str = "abc", structural: str = "def") -> FileFingerprint:
        return FileFingerprint(
            file_path="test.py", mtime=1.0, size=100,
            sha256=sha256, structural_hash=structural,
            symbols_hash="sym", imports_hash="imp", calls_hash="call",
        )

    def test_none_when_sha256_matches(self):
        fp = self._make_fp(sha256="same", structural="same")
        result = ChangeClassifier.classify(fp, fp)
        assert result == ChangeType.NONE

    def test_cosmetic_when_structural_matches_but_sha256_differs(self):
        current = self._make_fp(sha256="new_content", structural="same_struct")
        stored = self._make_fp(sha256="old_content", structural="same_struct")
        result = ChangeClassifier.classify(current, stored)
        assert result == ChangeType.COSMETIC

    def test_structural_when_structural_hash_differs(self):
        current = self._make_fp(sha256="new", structural="new_struct")
        stored = self._make_fp(sha256="old", structural="old_struct")
        result = ChangeClassifier.classify(current, stored)
        assert result == ChangeType.STRUCTURAL

    def test_added_when_no_stored_fingerprint(self):
        current = self._make_fp()
        result = ChangeClassifier.classify(current, None)
        assert result == ChangeType.ADDED

    def test_deleted_when_no_current_fingerprint(self):
        stored = self._make_fp()
        result = ChangeClassifier.classify(None, stored)
        assert result == ChangeType.DELETED

    def test_none_when_both_none(self):
        result = ChangeClassifier.classify(None, None)
        assert result == ChangeType.NONE


# ── Test compute_file_hashes ──────────────────────────────────────────────


class TestComputeFileHashes:
    """Tests for structural hash computation."""

    def test_base_file_hashes(self):
        fp = compute_file_hashes(_path("base_file.py"))
        assert fp.sha256
        assert fp.structural_hash
        assert fp.symbols_hash
        assert fp.imports_hash
        assert fp.calls_hash
        assert fp.mtime > 0
        assert fp.size > 0

    def test_cosmetic_comment_same_structural(self):
        """Comment-only changes should have the same structural hash."""
        base = compute_file_hashes(_path("base_file.py"))
        cosmetic = compute_file_hashes(_path("cosmetic_comment.py"))
        assert base.structural_hash == cosmetic.structural_hash
        assert base.symbols_hash == cosmetic.symbols_hash
        assert base.imports_hash == cosmetic.imports_hash
        assert base.calls_hash == cosmetic.calls_hash
        # But SHA256 must differ (file content changed)
        assert base.sha256 != cosmetic.sha256

    def test_cosmetic_whitespace_same_structural(self):
        """Whitespace-only changes should have the same structural hash."""
        base = compute_file_hashes(_path("base_file.py"))
        cosmetic = compute_file_hashes(_path("cosmetic_whitespace.py"))
        assert base.structural_hash == cosmetic.structural_hash
        assert base.symbols_hash == cosmetic.symbols_hash
        assert base.imports_hash == cosmetic.imports_hash
        assert base.calls_hash == cosmetic.calls_hash
        assert base.sha256 != cosmetic.sha256

    def test_cosmetic_docstring_same_structural(self):
        """Docstring-only changes should have the same structural hash."""
        base = compute_file_hashes(_path("base_file.py"))
        cosmetic = compute_file_hashes(_path("cosmetic_docstring.py"))
        assert base.structural_hash == cosmetic.structural_hash
        assert base.symbols_hash == cosmetic.symbols_hash
        assert base.imports_hash == cosmetic.imports_hash
        assert base.calls_hash == cosmetic.calls_hash
        assert base.sha256 != cosmetic.sha256

    def test_structural_signature_differs(self):
        """Function signature change should produce different structural hash."""
        base = compute_file_hashes(_path("base_file.py"))
        changed = compute_file_hashes(_path("structural_signature.py"))
        assert base.structural_hash != changed.structural_hash
        assert base.symbols_hash == changed.symbols_hash  # same symbols
        assert base.imports_hash == changed.imports_hash

    def test_structural_import_differs(self):
        """Import change should produce different imports hash."""
        base = compute_file_hashes(_path("base_file.py"))
        changed = compute_file_hashes(_path("structural_import.py"))
        assert base.imports_hash != changed.imports_hash
        assert base.structural_hash == changed.structural_hash  # same functions/classes

    def test_structural_call_differs(self):
        """Call target change should produce different calls hash."""
        base = compute_file_hashes(_path("base_file.py"))
        changed = compute_file_hashes(_path("structural_call.py"))
        assert changed.calls_hash != base.calls_hash

    def test_structural_new_function_differs(self):
        """New function should produce different structural and symbols hash."""
        base = compute_file_hashes(_path("base_file.py"))
        changed = compute_file_hashes(_path("structural_new_function.py"))
        assert base.structural_hash != changed.structural_hash
        assert base.symbols_hash != changed.symbols_hash

    def test_syntax_error_fallback(self):
        """Unparseable file uses SHA256 as fallback for structural hashes."""
        fp = compute_file_hashes(_path("syntax_error.py"))
        # All structural hashes should equal sha256 (fallback)
        assert fp.structural_hash == fp.sha256
        assert fp.symbols_hash == fp.sha256
        assert fp.imports_hash == fp.sha256
        assert fp.calls_hash == fp.sha256

    def test_compute_fingerprints_batch(self):
        """Batch fingerprint computation for multiple files."""
        files = [_path("base_file.py"), _path("cosmetic_comment.py")]
        fps = compute_fingerprints(FIXTURES_DIR, files)
        base_rel = "base_file.py"
        cosmetic_rel = "cosmetic_comment.py"
        assert base_rel in fps
        assert cosmetic_rel in fps
        assert fps[base_rel].sha256 != fps[cosmetic_rel].sha256
        assert fps[base_rel].structural_hash == fps[cosmetic_rel].structural_hash


# ── Test ChangeClassification End-to-End ──────────────────────────────────


class TestChangeClassificationEndToEnd:
    """End-to-end tests for classify → change type pipeline."""

    def test_base_vs_comment_classified_as_cosmetic(self):
        base = compute_file_hashes(_path("base_file.py"))
        comment = compute_file_hashes(_path("cosmetic_comment.py"))
        result = ChangeClassifier.classify(comment, base)
        assert result == ChangeType.COSMETIC

    def test_base_vs_whitespace_classified_as_cosmetic(self):
        base = compute_file_hashes(_path("base_file.py"))
        ws = compute_file_hashes(_path("cosmetic_whitespace.py"))
        result = ChangeClassifier.classify(ws, base)
        assert result == ChangeType.COSMETIC

    def test_base_vs_docstring_classified_as_cosmetic(self):
        base = compute_file_hashes(_path("base_file.py"))
        ds = compute_file_hashes(_path("cosmetic_docstring.py"))
        result = ChangeClassifier.classify(ds, base)
        assert result == ChangeType.COSMETIC

    def test_base_vs_signature_classified_as_structural(self):
        base = compute_file_hashes(_path("base_file.py"))
        sig = compute_file_hashes(_path("structural_signature.py"))
        result = ChangeClassifier.classify(sig, base)
        assert result == ChangeType.STRUCTURAL

    def test_base_vs_import_classified_as_structural(self):
        base = compute_file_hashes(_path("base_file.py"))
        imp = compute_file_hashes(_path("structural_import.py"))
        result = ChangeClassifier.classify(imp, base)
        assert result == ChangeType.STRUCTURAL

    def test_base_vs_call_classified_as_structural(self):
        base = compute_file_hashes(_path("base_file.py"))
        call = compute_file_hashes(_path("structural_call.py"))
        result = ChangeClassifier.classify(call, base)
        assert result == ChangeType.STRUCTURAL

    def test_base_vs_new_function_classified_as_structural(self):
        base = compute_file_hashes(_path("base_file.py"))
        newf = compute_file_hashes(_path("structural_new_function.py"))
        result = ChangeClassifier.classify(newf, base)
        assert result == ChangeType.STRUCTURAL

    def test_identical_file_classified_as_none(self):
        base = compute_file_hashes(_path("base_file.py"))
        result = ChangeClassifier.classify(base, base)
        assert result == ChangeType.NONE


# ── Test Stat Pre-Filter ──────────────────────────────────────────────────


class TestStatPreFilter:
    """Tests for mtime+size stat pre-filter optimization."""

    def test_unchanged_files_detected_by_mtime_size(self, tmp_path: Path):
        """Files with matching mtime+size should be marked as unchanged."""
        # Create test files
        f1 = tmp_path / "a.py"
        f1.write_text("print('hello')\n", encoding="utf-8")
        time.sleep(0.01)  # ensure different mtime
        f2 = tmp_path / "b.py"
        f2.write_text("print('world')\n", encoding="utf-8")

        # Build stored fingerprints
        fp1 = compute_file_hashes(f1)
        fp1.file_path = "a.py"
        fp2 = compute_file_hashes(f2)
        fp2.file_path = "b.py"
        stored = {"a.py": fp1, "b.py": fp2}

        # Both files unchanged
        unchanged, needs_hash, deleted = stat_prefilter(
            [f1, f2], tmp_path, stored,
        )
        assert len(unchanged) == 2
        assert len(needs_hash) == 0
        assert len(deleted) == 0

    def test_changed_file_needs_hash(self, tmp_path: Path):
        """File with different mtime should need re-hashing."""
        f1 = tmp_path / "a.py"
        f1.write_text("original\n", encoding="utf-8")
        fp1 = compute_file_hashes(f1)
        fp1.file_path = "a.py"
        stored = {"a.py": fp1}

        # Modify file
        time.sleep(0.01)  # ensure different mtime
        f1.write_text("modified content\n", encoding="utf-8")

        unchanged, needs_hash, deleted = stat_prefilter(
            [f1], tmp_path, stored,
        )
        assert len(unchanged) == 0
        assert len(needs_hash) == 1
        assert len(deleted) == 0

    def test_deleted_file_detected(self, tmp_path: Path):
        """File in stored fingerprints but not on disk should be marked deleted."""
        f1 = tmp_path / "a.py"
        f1.write_text("content\n", encoding="utf-8")
        fp1 = compute_file_hashes(f1)
        fp1.file_path = "a.py"
        stored = {"a.py": fp1, "deleted.py": fp1}

        unchanged, needs_hash, deleted = stat_prefilter(
            [f1], tmp_path, stored,
        )
        assert len(deleted) == 1
        assert "deleted.py" in deleted

    def test_new_file_not_in_stored(self, tmp_path: Path):
        """New file not in stored fingerprints should need hashing."""
        f1 = tmp_path / "new_file.py"
        f1.write_text("new\n", encoding="utf-8")

        unchanged, needs_hash, deleted = stat_prefilter(
            [f1], tmp_path, {},
        )
        assert len(needs_hash) == 1
        assert len(unchanged) == 0


# ── Test StatusResult with Classification ─────────────────────────────────


class TestStatusResult:
    """Tests for StatusResult with classification fields."""

    def test_status_result_with_classification(self):
        result = StatusResult(
            status="stale",
            structural_files=["a.py"],
            cosmetic_files=["b.py"],
            added_files=["c.py"],
            deleted_files=["d.py"],
            change_summary={
                "none": 0, "cosmetic": 1, "structural": 1,
                "added": 1, "deleted": 1,
            },
        )
        assert result.structural_files == ["a.py"]
        assert result.cosmetic_files == ["b.py"]
        assert result.added_files == ["c.py"]
        assert result.deleted_files == ["d.py"]
        # changed_files should be union of structural + cosmetic
        assert "a.py" in result.changed_files
        assert "b.py" in result.changed_files
        # changed_files = union(structural + cosmetic) = 2, added = 1, deleted = 1
        assert result.total_changes == 4

    def test_status_result_backward_compat(self):
        """Legacy use without classification fields still works."""
        result = StatusResult(
            status="stale",
            changed_files=["x.py", "y.py"],
        )
        assert result.changed_files == ["x.py", "y.py"]
        assert result.cosmetic_files == []
        assert result.structural_files == []
        assert result.change_summary["none"] == 0


# ── Test IncrementalIndex with Classification ─────────────────────────────


class TestIncrementalWithClassification:
    """Tests for incremental index integration with fingerprint classification."""

    def test_cosmetic_change_not_reindexed(self, tmp_path: Path):
        """Cosmetic-only changes should not trigger graph rebuild."""
        from codegraph.indexer.fingerprint import FingerprintStore
        from codegraph.graph.models import IndexMetadata, FileEntry, GraphNode, GraphEdge
        from codegraph.storage.file_store import FileStore

        # Setup: create a project with one file
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()

        py_file = src_dir / "app.py"
        py_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

        # Create metadata
        from codegraph.indexer.scanner import compute_fingerprint, normalize_path
        rel = normalize_path(py_file.relative_to(tmp_path))
        metadata = IndexMetadata(
            schema_version="1.0.0",
            indexer_version="1.0.0",
            root_path=str(tmp_path),
            indexed_at="2024-01-01T00:00:00Z",
            file_count=1,
            symbol_count=1,
            edge_count=0,
            files=[FileEntry(
                path=rel,
                fingerprint=compute_fingerprint(py_file),
                indexed_at="2024-01-01T00:00:00Z",
            )],
        )
        store = FileStore(cg_dir)
        store.save_metadata(metadata)

        # Create nodes/edges for the indexed file
        store.save_nodes([{
            "id": f"{rel}::hello", "type": "function", "name": "hello",
            "file_path": rel, "module": "src.app",
            "location": {"line": 1, "col": 0},
        }])
        store.save_edges([])

        # Write initial fingerprints (base version of the file)
        from codegraph.indexer.fingerprint import compute_fingerprints as cfp
        fps = cfp(tmp_path, [py_file])
        fp_store = FingerprintStore(cg_dir)
        fp_store.save(fps)

        # Now make a cosmetic change (add a comment)
        py_file.write_text(
            "def hello():\n    # a comment\n    return 'world'\n",
            encoding="utf-8",
        )

        # Run classification-based detection
        result = detect_status_with_classification(tmp_path, metadata, fp_store)
        assert result.status == "stale"
        # Should be classified as cosmetic (only comment added, same function signature)
        assert len(result.cosmetic_files) >= 1
        assert len(result.structural_files) == 0

    def test_structural_change_triggers_reindex(self, tmp_path: Path):
        """Structural changes should be flagged for re-indexing."""
        from codegraph.indexer.fingerprint import FingerprintStore
        from codegraph.graph.models import IndexMetadata, FileEntry
        from codegraph.storage.file_store import FileStore

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()

        py_file = src_dir / "app.py"
        py_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

        from codegraph.indexer.scanner import compute_fingerprint, normalize_path
        rel = normalize_path(py_file.relative_to(tmp_path))
        metadata = IndexMetadata(
            schema_version="1.0.0",
            indexer_version="1.0.0",
            root_path=str(tmp_path),
            indexed_at="2024-01-01T00:00:00Z",
            file_count=1,
            symbol_count=1,
            edge_count=0,
            files=[FileEntry(
                path=rel,
                fingerprint=compute_fingerprint(py_file),
                indexed_at="2024-01-01T00:00:00Z",
            )],
        )
        store = FileStore(cg_dir)
        store.save_metadata(metadata)
        store.save_nodes([{
            "id": f"{rel}::hello", "type": "function", "name": "hello",
            "file_path": rel, "module": "src.app",
            "location": {"line": 1, "col": 0},
        }])
        store.save_edges([])

        from codegraph.indexer.fingerprint import compute_fingerprints as cfp
        fps = cfp(tmp_path, [py_file])
        fp_store = FingerprintStore(cg_dir)
        fp_store.save(fps)

        # Now make a structural change (rename function)
        py_file.write_text("def goodbye():\n    return 'world'\n", encoding="utf-8")

        result = detect_status_with_classification(tmp_path, metadata, fp_store)
        assert result.status == "stale"
        assert len(result.structural_files) >= 1

    def test_new_file_classified_as_added(self, tmp_path: Path):
        """New file should be classified as ADDED."""
        from codegraph.indexer.fingerprint import FingerprintStore
        from codegraph.graph.models import IndexMetadata, FileEntry
        from codegraph.storage.file_store import FileStore

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()

        # Existing file
        f1 = src_dir / "existing.py"
        f1.write_text("def foo():\n    pass\n", encoding="utf-8")

        from codegraph.indexer.scanner import compute_fingerprint, normalize_path
        rel = normalize_path(f1.relative_to(tmp_path))
        metadata = IndexMetadata(
            schema_version="1.0.0",
            indexer_version="1.0.0",
            root_path=str(tmp_path),
            indexed_at="2024-01-01T00:00:00Z",
            file_count=1,
            symbol_count=1,
            edge_count=0,
            files=[FileEntry(
                path=rel,
                fingerprint=compute_fingerprint(f1),
                indexed_at="2024-01-01T00:00:00Z",
            )],
        )
        store = FileStore(cg_dir)
        store.save_metadata(metadata)
        store.save_nodes([{
            "id": f"{rel}::foo", "type": "function", "name": "foo",
            "file_path": rel, "module": "src.existing",
            "location": {"line": 1, "col": 0},
        }])
        store.save_edges([])

        from codegraph.indexer.fingerprint import compute_fingerprints as cfp
        fps = cfp(tmp_path, [f1])
        fp_store = FingerprintStore(cg_dir)
        fp_store.save(fps)

        # Add new file
        f2 = src_dir / "new_file.py"
        f2.write_text("def bar():\n    pass\n", encoding="utf-8")

        result = detect_status_with_classification(tmp_path, metadata, fp_store)
        assert len(result.added_files) >= 1

    def test_deleted_file_classified_as_deleted(self, tmp_path: Path):
        """Deleted file should be classified as DELETED."""
        from codegraph.indexer.fingerprint import FingerprintStore
        from codegraph.graph.models import IndexMetadata, FileEntry
        from codegraph.storage.file_store import FileStore

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()

        # Create two files, index one, then delete one that was in metadata
        f1 = src_dir / "keep.py"
        f1.write_text("def foo():\n    pass\n", encoding="utf-8")
        f2 = src_dir / "remove.py"
        f2.write_text("def bar():\n    pass\n", encoding="utf-8")

        from codegraph.indexer.scanner import compute_fingerprint, normalize_path
        rel1 = normalize_path(f1.relative_to(tmp_path))
        rel2 = normalize_path(f2.relative_to(tmp_path))

        # Metadata includes both files
        metadata = IndexMetadata(
            schema_version="1.0.0",
            indexer_version="1.0.0",
            root_path=str(tmp_path),
            indexed_at="2024-01-01T00:00:00Z",
            file_count=2,
            symbol_count=2,
            edge_count=0,
            files=[
                FileEntry(path=rel1, fingerprint=compute_fingerprint(f1), indexed_at=""),
                FileEntry(path=rel2, fingerprint=compute_fingerprint(f2), indexed_at=""),
            ],
        )
        store = FileStore(cg_dir)
        store.save_metadata(metadata)
        store.save_nodes([
            {"id": f"{rel1}::foo", "type": "function", "name": "foo",
             "file_path": rel1, "module": "src.keep", "location": {"line": 1, "col": 0}},
            {"id": f"{rel2}::bar", "type": "function", "name": "bar",
             "file_path": rel2, "module": "src.remove", "location": {"line": 1, "col": 0}},
        ])
        store.save_edges([])

        from codegraph.indexer.fingerprint import compute_fingerprints as cfp
        fps = cfp(tmp_path, [f1, f2])
        fp_store = FingerprintStore(cg_dir)
        fp_store.save(fps)

        # Delete f2
        f2.unlink()

        result = detect_status_with_classification(tmp_path, metadata, fp_store)
        assert len(result.deleted_files) == 1
        assert result.deleted_files[0] == rel2


# ── Test Doctor Fingerprint Check ─────────────────────────────────────────


class TestDoctorFingerprintCheck:
    """Tests for doctor command fingerprint health checks."""

    def test_fingerprint_missing_detected(self, tmp_path: Path):
        """Doctor should warn when fingerprints.json is missing."""
        from codegraph.storage.integrity import check_storage_integrity

        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        # Create minimal valid index files
        (cg_dir / "nodes.json").write_text("[]", encoding="utf-8")
        (cg_dir / "edges.json").write_text("[]", encoding="utf-8")
        from codegraph.graph.models import IndexMetadata
        meta = IndexMetadata(
            schema_version="1.0.0", indexer_version="1.0.0",
            root_path=str(tmp_path), indexed_at="2024-01-01T00:00:00Z",
            file_count=0, symbol_count=0, edge_count=0, files=[],
        )
        (cg_dir / "metadata.json").write_text(meta.model_dump_json(), encoding="utf-8")

        integrity = check_storage_integrity(cg_dir)
        # Should have a warning about fingerprints
        fp_checks = [c for c in integrity["checks"] if "fingerprint" in c.get("name", "")]
        assert len(fp_checks) >= 1
        assert any(c["status"] in ("warning", "error") for c in fp_checks
                   if "missing" in c.get("message", "").lower())


# ── Test Full Rebuild Recommendation ──────────────────────────────────────


class TestFullRebuildRecommendation:
    """Tests for full rebuild threshold recommendation logic."""

    def test_threshold_below_30_no_recommendation(self):
        from codegraph.indexer.incremental import (
            FULL_REBUILD_FILE_THRESHOLD,
            FULL_REBUILD_RATIO_THRESHOLD,
        )
        structural_count = 5
        total_files = 100
        recommend = (
            structural_count > FULL_REBUILD_FILE_THRESHOLD
            or structural_count > FULL_REBUILD_RATIO_THRESHOLD * total_files
        )
        assert not recommend

    def test_threshold_above_30_recommends_rebuild(self):
        from codegraph.indexer.incremental import FULL_REBUILD_FILE_THRESHOLD
        structural_count = 31
        assert structural_count > FULL_REBUILD_FILE_THRESHOLD

    def test_threshold_above_30_percent_recommends_rebuild(self):
        from codegraph.indexer.incremental import FULL_REBUILD_RATIO_THRESHOLD
        structural_count = 4
        total_files = 10
        recommend = structural_count > FULL_REBUILD_RATIO_THRESHOLD * total_files
        assert recommend
