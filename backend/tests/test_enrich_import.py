"""Tests for enrichment import module."""

import json
from pathlib import Path
import pytest
from codegraph.enrich.models import AgentOutput, EnrichedFile, EnrichedSymbol, EnrichedEvidence
from codegraph.enrich.import_enrich import import_enrichment
from codegraph.storage.sqlite_store import SqliteStore


def _write_agent_output(tmp_path: Path, output: AgentOutput) -> Path:
    p = tmp_path / "enrich_output.json"
    p.write_text(output.model_dump_json(indent=2), encoding="utf-8")
    return p


class TestImportEnrichment:
    def test_import_file_enrichment(self, populated_store, tmp_path):
        sqlite_path = tmp_path / "index.sqlite"
        sqlite = SqliteStore(sqlite_path)
        sqlite.initialize()
        # Save sample nodes to SQLite
        nodes = [
            {
                "id": n.id,
                "type": n.type,
                "name": n.name,
                "file_path": n.file_path,
            }
            for n in populated_store.all_nodes()
        ]
        sqlite.save_nodes(nodes)
        sqlite.close()

        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            files=[
                EnrichedFile(
                    path="app/api/auth.py",
                    summary="Authentication API module",
                    tags=["auth", "security"],
                    role="service",
                    confidence="high",
                    evidence=[EnrichedEvidence(file="app/api/auth.py", line_start=1, line_end=20)],
                )
            ],
        )
        p = _write_agent_output(tmp_path, output)

        sqlite = SqliteStore(sqlite_path)
        sqlite.initialize()
        stats = import_enrichment(p, populated_store, sqlite)
        assert stats["file_count"] == 1
        assert stats["symbol_count"] == 0
        assert stats["enriched_at"]

        # Verify enrichment was written
        node = sqlite.get_node("app/api/auth.py")
        assert node is not None
        assert node.get("summary") == "Authentication API module"
        assert node.get("role") == "service"
        assert node.get("enrichment_confidence") == "high"
        assert node.get("enrichment_status") == "analyzed"

        # Verify meta entries
        assert sqlite.get_meta("enrichment_file_count") == "1"
        sqlite.close()

    def test_import_symbol_enrichment(self, populated_store, tmp_path):
        sqlite_path = tmp_path / "index.sqlite"
        sqlite = SqliteStore(sqlite_path)
        sqlite.initialize()
        nodes = [
            {"id": n.id, "type": n.type, "name": n.name, "file_path": n.file_path}
            for n in populated_store.all_nodes()
        ]
        sqlite.save_nodes(nodes)
        sqlite.close()

        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            symbols=[
                EnrichedSymbol(
                    symbol="login",
                    file="app/api/auth.py",
                    summary="Authenticate user and return token",
                    responsibilities=["Validate credentials", "Issue token"],
                    edge_cases=["Empty credentials", "Locked account"],
                    test_relevance="Test invalid credentials and token expiry",
                    confidence="high",
                    evidence=[EnrichedEvidence(file="app/api/auth.py", line_start=6, line_end=9)],
                )
            ],
        )
        p = _write_agent_output(tmp_path, output)

        sqlite = SqliteStore(sqlite_path)
        sqlite.initialize()
        stats = import_enrichment(p, populated_store, sqlite)
        assert stats["symbol_count"] == 1

        node = sqlite.get_node("app/api/auth.py::login")
        assert node is not None
        assert node.get("summary") == "Authenticate user and return token"
        assert len(node.get("responsibilities", [])) == 2
        assert len(node.get("edge_cases", [])) == 2
        assert node.get("enrichment_status") == "analyzed"
        sqlite.close()

    def test_import_missing_symbol_skips(self, populated_store, tmp_path):
        sqlite_path = tmp_path / "index.sqlite"
        sqlite = SqliteStore(sqlite_path)
        sqlite.initialize()
        nodes = [
            {"id": n.id, "type": n.type, "name": n.name, "file_path": n.file_path}
            for n in populated_store.all_nodes()
        ]
        sqlite.save_nodes(nodes)
        sqlite.close()

        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            symbols=[
                EnrichedSymbol(
                    symbol="does_not_exist",
                    file="app/api/auth.py",
                    summary="Test",
                    confidence="low",
                )
            ],
        )
        p = _write_agent_output(tmp_path, output)

        sqlite = SqliteStore(sqlite_path)
        sqlite.initialize()
        stats = import_enrichment(p, populated_store, sqlite)
        assert stats["symbol_count"] == 0  # skipped because symbol not found
        sqlite.close()

    def test_import_preserves_existing_tags(self, populated_store, tmp_path):
        sqlite_path = tmp_path / "index.sqlite"
        sqlite = SqliteStore(sqlite_path)
        sqlite.initialize()
        # Node with existing tags — both in SQLite and in-memory store
        login_node = populated_store.get_node("app/api/auth.py::login")
        if login_node:
            login_node.tags = ["existing"]
        nodes = [
            {"id": n.id, "type": n.type, "name": n.name, "file_path": n.file_path,
             "tags": getattr(n, "tags", []) if hasattr(n, "tags") else []}
            for n in populated_store.all_nodes()
        ]
        sqlite.save_nodes(nodes)
        sqlite.close()

        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            symbols=[
                EnrichedSymbol(
                    symbol="login",
                    file="app/api/auth.py",
                    summary="Login",
                    confidence="high",
                )
            ],
        )
        p = _write_agent_output(tmp_path, output)

        sqlite = SqliteStore(sqlite_path)
        sqlite.initialize()
        import_enrichment(p, populated_store, sqlite)
        node = sqlite.get_node("app/api/auth.py::login")
        assert node is not None
        assert "existing" in node.get("tags", [])
        sqlite.close()
