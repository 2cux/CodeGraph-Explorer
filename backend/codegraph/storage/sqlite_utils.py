"""SQLite utility functions — chunking, safe batch writes.

Centralises chunking logic so that large node/edge batches never hit
SQLite's ``SQLITE_MAX_VARIABLE_NUMBER`` limit (default 999 on most builds).
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterator, Sequence, TypeVar

T = TypeVar("T")

# SQLite default max variable number is 999.  A single row in the nodes
# table uses 15 bound parameters and an edge row uses 7.  We pick a
# conservative chunk size that keeps us well below even 1-param queries.
DEFAULT_CHUNK_SIZE = 500


def chunked(iterable: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    """Yield successive *size*-sized chunks from *iterable*."""
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]


def safe_executemany(
    conn: sqlite3.Connection,
    sql: str,
    rows: list[Any],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> int:
    """Execute *sql* with ``executemany``, splitting *rows* into safe chunks.

    Returns the total number of rows written.
    """
    total = 0
    for batch in chunked(rows, chunk_size):
        conn.executemany(sql, batch)
        total += len(batch)
    return total


def safe_execute_chunked(
    conn: sqlite3.Connection,
    sql: str,
    rows: list[dict[str, Any]],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> int:
    """Execute *sql* once per chunk using ``execute`` + parameter binding.

    This variant is useful when the parameter count per row varies or when
    the query template uses named placeholders.
    """
    total = 0
    for batch in chunked(rows, chunk_size):
        conn.executemany(sql, batch)
        total += len(batch)
    return total
