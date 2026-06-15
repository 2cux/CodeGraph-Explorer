"""Clear all enrichment data from the SQLite store.

Resets enrichment columns to defaults and removes enrichment meta keys.
"""

from __future__ import annotations

from codegraph.storage.sqlite_store import SqliteStore


def clear_enrichment(sqlite_store: SqliteStore) -> int:
    """Reset all enrichment columns to defaults.

    Args:
        sqlite_store: The SQLite store to clear.

    Returns:
        Number of nodes cleared.
    """
    return sqlite_store.clear_enrichment()
