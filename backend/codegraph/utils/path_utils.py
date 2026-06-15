"""Shared path classification utilities.

Centralizes test-path detection, production-path detection and query
intent analysis so every ranking/scoring layer applies the same rules.

Used by:
- ``codegraph.storage.sqlite_store`` — search sort key
- ``codegraph.graph.query`` — in-memory search fallback
- ``codegraph.context.ranking`` — entry point relevance scoring
- ``codegraph.mcp_server`` — scan output classification
"""

import re

# ── Test / spec / fixture / mock path patterns ──────────────────────────

_TEST_PATTERNS: list[str] = [
    # Directory-based test/spec/fixture paths
    r"(?:^|/)tests/",
    r"(?:^|/)test/",
    r"(?:^|/)__tests__/",
    r"(?:^|/)spec/",
    r"(?:^|/)fixtures?/",
    r"(?:^|/)mocks?/",
    r"(?:^|/)__mocks__/",
    # File naming conventions
    r"_test\.\w+$",
    r"^test_",
    r"test_[\w]*\.\w+$",
    r"^conftest\.",
    r"^setup\.",
    r"^teardown\.",
    r"^fixtures?\.",
    r"__test__",
]

_TEST_RE = re.compile("|".join(_TEST_PATTERNS))

# ── Production source root patterns ─────────────────────────────────────

_PROD_ROOTS: tuple[str, ...] = (
    "/src/", "/app/", "/lib/", "/main/", "/pkg/", "/cmd/",
    "/controllers/", "/services/", "/models/", "/routes/",
    "/handlers/", "/middleware/", "/utils/", "/core/",
    "/api/", "/domain/", "/infrastructure/", "/application/",
)

# ── Test intent query terms ─────────────────────────────────────────────

_TEST_INTENT_TERMS: tuple[str, ...] = (
    "test", "tests", "testing",
    "spec",
    "coverage",
    "assert", "assertion",
    "mock", "mocking", "mockery",
    "fixture", "fixtures", "conftest",
    "pytest", "unittest", "jest", "vitest", "mocha",
)

# ── Framework entry point patterns ─────────────────────────────────────

# Node types that are framework entry points
FW_ENTRY_TYPES: frozenset[str] = frozenset({
    "route", "controller", "service", "component",
})

# Tags that indicate a framework entry point
FW_ENTRY_TAGS: frozenset[str] = frozenset({
    "route", "controller", "service", "handler", "command", "cli",
})

# Names that suggest a framework entry point
_FW_ENTRY_NAME_RE = re.compile(
    r'^(main|app|server|handler|router|middleware|'
    r'command|run|start|init|bootstrap|setup)$',
    re.IGNORECASE,
)

# Path patterns indicating framework entry points
FW_ENTRY_PATHS: tuple[str, ...] = (
    "/main.py", "/app.py", "/server.py", "/routes.py",
    "/handlers/", "/controllers/", "/middleware/",
    "/router/", "/commands/",
)

FW_ENTRY_NAMES: frozenset[str] = frozenset({
    "main", "app", "server", "handler",
})


def is_framework_entry_point(
    *,
    node_type: str = "",
    tags: list[str] | None = None,
    framework_id: str | None = None,
    name: str = "",
    file_path: str = "",
) -> bool:
    """True if the described symbol is a framework entry point.

    Accepts keyword arguments so callers can pass either a ``GraphNode``
    or a plain ``dict`` item without needing separate implementations.
    """
    if node_type in FW_ENTRY_TYPES:
        return True
    if tags and any(t in FW_ENTRY_TAGS for t in tags):
        return True
    if framework_id and framework_id != "unknown":
        return True
    if name and name.lower() in FW_ENTRY_NAMES:
        return True
    if name and _FW_ENTRY_NAME_RE.search(name):
        return True
    if file_path:
        fp = file_path.replace("\\", "/").lower()
        if any(p in fp for p in FW_ENTRY_PATHS):
            return True
    return False


def is_test_path(file_path: str) -> bool:
    """True if *file_path* looks like a test/spec/fixture/mock file.

    >>> is_test_path("tests/test_auth.py")
    True
    >>> is_test_path("src/app/api/auth.py")
    False
    >>> is_test_path("spec/models/user_spec.rb")
    True
    """
    if not file_path:
        return False
    normalized = file_path.replace("\\", "/").lower()
    return bool(_TEST_RE.search(normalized))


def is_production_path(file_path: str) -> bool:
    """True if *file_path* is under a conventional production source root.

    >>> is_production_path("src/app/api/auth.py")
    True
    >>> is_production_path("tests/test_auth.py")
    False
    """
    if not file_path:
        return False
    normalized = file_path.replace("\\", "/").lower()
    return any(root in normalized for root in _PROD_ROOTS)


def is_test_intent_query(query: str) -> bool:
    """True if the query text mentions test-related terms.

    >>> is_test_intent_query("fix login bug")
    False
    >>> is_test_intent_query("add unit tests for login")
    True
    >>> is_test_intent_query("improve test coverage for auth module")
    True
    """
    if not query:
        return False
    q = query.lower()
    return any(term in q for term in _TEST_INTENT_TERMS)
