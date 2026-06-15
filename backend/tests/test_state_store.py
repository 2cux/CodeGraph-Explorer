"""Tests for per-file pending change models and state store v2 methods."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraph.storage.pending_models import PendingChangeSet, PendingFileChange
from codegraph.storage.state_store import IndexStateStore


# ── PendingFileChange model tests ─────────────────────────────────────


class TestPendingFileChange:
    """Tests for the PendingFileChange Pydantic model."""

    def test_create_minimal(self):
        pc = PendingFileChange(file_path="test/file.py")
        assert pc.file_path == "test/file.py"
        assert pc.mtime == 0.0
        assert pc.synced is False
        assert pc.affected_symbols == []
        assert pc.appeared_in_response is False
        assert pc.change_type == ""

    def test_create_full(self):
        pc = PendingFileChange(
            file_path="src/auth.py",
            mtime=1234567890.0,
            synced=True,
            affected_symbols=["login", "logout"],
            appeared_in_response=True,
            change_type="structural",
        )
        assert pc.file_path == "src/auth.py"
        assert pc.mtime == 1234567890.0
        assert pc.synced is True
        assert pc.affected_symbols == ["login", "logout"]
        assert pc.appeared_in_response is True
        assert pc.change_type == "structural"

    def test_model_serialization(self):
        pc = PendingFileChange(
            file_path="x.py",
            mtime=100.0,
            change_type="architecture",
        )
        data = pc.model_dump()
        assert data["file_path"] == "x.py"
        assert data["mtime"] == 100.0
        assert data["change_type"] == "architecture"

    def test_model_deserialization(self):
        data = {
            "file_path": "y.py",
            "mtime": 200.0,
            "synced": True,
            "affected_symbols": ["foo"],
            "appeared_in_response": False,
            "change_type": "added",
        }
        pc = PendingFileChange.model_validate(data)
        assert pc.file_path == "y.py"
        assert pc.change_type == "added"
        assert pc.affected_symbols == ["foo"]


# ── PendingChangeSet model tests ──────────────────────────────────────


class TestPendingChangeSet:
    """Tests for the PendingChangeSet container model."""

    def test_empty(self):
        cs = PendingChangeSet()
        assert cs.total == 0
        assert cs.breakdown() == {}
        assert cs.unsynced() == []

    def test_total(self):
        cs = PendingChangeSet(
            changed=[PendingFileChange(file_path="a.py")],
            added=[PendingFileChange(file_path="b.py")],
            deleted=[PendingFileChange(file_path="c.py")],
        )
        assert cs.total == 3

    def test_breakdown(self):
        cs = PendingChangeSet(
            changed=[
                PendingFileChange(file_path="a.py", change_type="structural"),
                PendingFileChange(file_path="b.py", change_type="architecture"),
            ],
            added=[PendingFileChange(file_path="c.py", change_type="added")],
            deleted=[PendingFileChange(file_path="d.py", change_type="deleted")],
        )
        bd = cs.breakdown()
        assert bd == {
            "structural": 1,
            "architecture": 1,
            "added": 1,
            "deleted": 1,
        }

    def test_unsynced(self):
        cs = PendingChangeSet(
            changed=[
                PendingFileChange(file_path="a.py", synced=True),
                PendingFileChange(file_path="b.py", synced=False),
            ],
        )
        unsynced = cs.unsynced()
        assert len(unsynced) == 1
        assert unsynced[0].file_path == "b.py"


# ── IndexStateStore v2 methods ────────────────────────────────────────


class TestIndexStateStoreV2:
    """Tests for the new per-file pending change methods."""

    def test_set_and_get_v2(self, tmp_path: Path):
        store = IndexStateStore(tmp_path)
        store.set_pending_changes_v2(
            changed=[PendingFileChange(
                file_path="src/changed.py",
                mtime=100.0,
                change_type="structural",
            )],
            added=[PendingFileChange(
                file_path="src/new.py",
                mtime=200.0,
                change_type="added",
            )],
            deleted=[PendingFileChange(
                file_path="src/removed.py",
                mtime=0.0,
                change_type="deleted",
            )],
        )

        cs = store.get_pending_changes()
        assert cs.total == 3
        assert len(cs.changed) == 1
        assert cs.changed[0].file_path == "src/changed.py"
        assert cs.changed[0].change_type == "structural"
        assert len(cs.added) == 1
        assert cs.added[0].file_path == "src/new.py"
        assert len(cs.deleted) == 1

    def test_mark_appeared_in_response(self, tmp_path: Path):
        store = IndexStateStore(tmp_path)
        store.set_pending_changes_v2(
            changed=[
                PendingFileChange(file_path="a.py"),
                PendingFileChange(file_path="b.py"),
            ],
            added=[],
            deleted=[],
        )

        store.mark_appeared_in_response({"a.py"})
        cs = store.get_pending_changes()
        assert cs.changed[0].appeared_in_response is True
        assert cs.changed[1].appeared_in_response is False

    def test_clear_pending(self, tmp_path: Path):
        store = IndexStateStore(tmp_path)
        store.set_pending_changes_v2(
            changed=[PendingFileChange(file_path="x.py")],
            added=[],
            deleted=[],
        )
        store.clear_pending_changes()
        cs = store.get_pending_changes()
        assert cs.total == 0


# ── Backward compatibility ────────────────────────────────────────────


class TestBackwardCompatibility:
    """Tests that old flat-string format is auto-upgraded."""

    def test_legacy_flat_format(self, tmp_path: Path):
        """Old format: pending_changes stores flat string lists."""
        store = IndexStateStore(tmp_path)

        # Simulate old format directly in state.json
        old_state = store.load()
        old_state["pending_changes"] = {
            "changed": ["src/a.py", "src/b.py"],
            "added": ["src/new.py"],
            "deleted": [],
        }
        store.save(old_state)

        cs = store.get_pending_changes()
        assert cs.total == 3
        assert len(cs.changed) == 2
        # Auto-upgraded entries should have default values
        for pc in cs.changed:
            assert isinstance(pc, PendingFileChange)
            assert pc.file_path in ("src/a.py", "src/b.py")
            assert pc.mtime == 0.0
            assert pc.synced is False

    def test_mixed_format_graceful(self, tmp_path: Path):
        """Mixed old and new formats — malformed entries skipped."""
        store = IndexStateStore(tmp_path)

        old_state = store.load()
        old_state["pending_changes"] = {
            "changed": [
                "src/legacy.py",  # old format
                {"file_path": "src/new_format.py", "change_type": "structural"},  # new format
            ],
            "added": [],
            "deleted": [42],  # invalid entry — should be skipped
        }
        store.save(old_state)

        cs = store.get_pending_changes()
        assert cs.total == 2  # legacy + new_format, invalid skipped
