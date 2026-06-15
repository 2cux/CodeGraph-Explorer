"""Query enrichment status from the SQLite store.

Provides statistics on enrichment coverage: how many nodes/files
have been enriched, confidence breakdown, and last import time.
"""

from __future__ import annotations

from codegraph.enrich.models import EnrichmentStatus
from codegraph.storage.sqlite_store import SqliteStore


def get_enrichment_status(sqlite_store: SqliteStore) -> EnrichmentStatus:
    """Query enrichment statistics from the SQLite store.

    Args:
        sqlite_store: The SQLite store to query.

    Returns:
        An ``EnrichmentStatus`` with counts and breakdowns.
    """
    raw = sqlite_store.get_enrichment_status()
    return EnrichmentStatus(
        total_nodes=raw.get("total_nodes", 0),
        enriched_nodes=raw.get("enriched_nodes", 0),
        pending_nodes=raw.get("pending_nodes", 0),
        skipped_nodes=raw.get("skipped_nodes", 0),
        error_nodes=raw.get("error_nodes", 0),
        enriched_files=raw.get("enriched_files", 0),
        total_files=raw.get("total_files", 0),
        confidence_breakdown=raw.get("confidence_breakdown", {}),
        last_enriched_at=raw.get("last_enriched_at", ""),
    )
