"""Tests for IntermediateStore — batch enrichment and validation artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.storage.intermediate_store import IntermediateStore


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> IntermediateStore:
    """Create an IntermediateStore pointing at a temp .codegraph dir."""
    return IntermediateStore(tmp_path / ".codegraph")


# ── Batch file tests ──────────────────────────────────────────────────


class TestBatchFiles:
    """Tests for write_batch, read_batch, list_batches, latest_batch."""

    def test_write_and_read_batch(self, store: IntermediateStore):
        data = {
            "files": [{"path": "a.py", "summary": "test"}],
            "symbols": [{"symbol": "foo", "file": "a.py"}],
            "enriched_at": "2026-06-15T00:00:00",
        }
        path = store.write_batch("prepare", data)
        assert path.exists()
        assert "enrich-batch-" in path.name
        assert "-prepare" in path.name

        # Read back
        loaded = store.read_batch(path)
        assert loaded is not None
        assert loaded["files"][0]["path"] == "a.py"
        assert loaded["symbols"][0]["symbol"] == "foo"

    def test_read_batch_missing(self, store: IntermediateStore):
        result = store.read_batch(Path("nonexistent.json"))
        assert result is None

    def test_list_batches_empty(self, store: IntermediateStore):
        assert store.list_batches() == []
        assert store.latest_batch() is None

    def test_list_batches_sorted(self, store: IntermediateStore):
        store.write_batch("old", {"files": [], "symbols": []})
        store.write_batch("new", {"files": [], "symbols": []})
        batches = store.list_batches()
        assert len(batches) == 2
        # Newest first (sorted by mtime)
        assert "-new" in batches[0].name

    def test_latest_batch(self, store: IntermediateStore):
        assert store.latest_batch() is None
        p1 = store.write_batch("first", {"files": [], "symbols": []})
        assert store.latest_batch() == p1


# ── Validation report tests ───────────────────────────────────────────


class TestValidationReport:
    """Tests for write_validation_report and read_validation_report."""

    def test_write_dict(self, store: IntermediateStore):
        path = store.write_validation_report({
            "valid": True,
            "errors": [],
            "stats": {"total_errors": 0},
        })
        assert path.exists()
        assert path.name == "validation-report.json"

    def test_write_pydantic_model(self, store: IntermediateStore):
        from codegraph.enrich.models import ValidationResult
        vr = ValidationResult(
            valid=True,
            errors=[],
            warnings=[],
            stats={"total": 5},
        )
        path = store.write_validation_report(vr)
        assert path.exists()

    def test_read_back(self, store: IntermediateStore):
        store.write_validation_report({"valid": False, "errors": [{"msg": "bad"}]})
        loaded = store.read_validation_report()
        assert loaded is not None
        assert loaded["valid"] is False
        assert len(loaded["errors"]) == 1

    def test_read_missing(self, store: IntermediateStore):
        assert store.read_validation_report() is None


# ── Audit trail tests ─────────────────────────────────────────────────


class TestAuditTrail:
    """Tests for audit_trail()."""

    def test_empty(self, store: IntermediateStore):
        assert store.audit_trail() == []

    def test_with_batches(self, store: IntermediateStore):
        store.write_batch("batch-a", {
            "files": [{"a": 1}, {"b": 2}],
            "symbols": [{"x": 1}],
            "enriched_at": "2026-06-15T01:00:00",
        })
        store.write_batch("batch-b", {
            "files": [{"c": 3}],
            "symbols": [{"y": 2}, {"z": 3}],
            "enriched_at": "2026-06-15T02:00:00",
        })
        trail = store.audit_trail()
        assert len(trail) == 2
        # Check that both batches appear (order depends on mtime resolution)
        found_files = {entry["file_count"] for entry in trail}
        found_symbols = {entry["symbol_count"] for entry in trail}
        assert found_files == {"1", "2"}
        assert found_symbols == {"1", "2"}


# ── Prune tests ───────────────────────────────────────────────────────


class TestPrune:
    """Tests for prune_batches()."""

    def test_prune_keeps_recent(self, store: IntermediateStore):
        for i in range(5):
            store.write_batch(f"batch-{i}", {"files": [], "symbols": []})
        assert len(store.list_batches()) == 5

        removed = store.prune_batches(keep=3)
        assert removed == 2
        assert len(store.list_batches()) == 3

    def test_prune_more_than_exist(self, store: IntermediateStore):
        store.write_batch("only", {"files": [], "symbols": []})
        removed = store.prune_batches(keep=10)
        assert removed == 0
        assert len(store.list_batches()) == 1


# ── Clear tests ───────────────────────────────────────────────────────


class TestClearAll:
    """Tests for clear_all()."""

    def test_clear_all(self, store: IntermediateStore):
        store.write_batch("batch", {"files": [], "symbols": []})
        store.write_validation_report({"valid": True})
        count = store.clear_all()
        assert count == 2
        assert store.list_batches() == []
        assert store.read_validation_report() is None

    def test_clear_empty(self, store: IntermediateStore):
        assert store.clear_all() == 0
