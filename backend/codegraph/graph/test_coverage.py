"""Test coverage signal computation.

Detects test files via filesystem heuristics (independent of indexing) and
analyzes ``tested_by`` edges to produce a structured signal that distinguishes:

* No test files detected at all
* Test files detected but no tested_by edges linking them to production symbols
* Low-confidence tested_by edges
* High-confidence tested_by edges

The goal is to avoid misleading agents with a bare ``test_files: 0`` when
test files actually exist on disk but aren't linked by the index.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from codegraph.graph.models import EdgeType, GraphEdge, GraphNode, NodeType
from codegraph.graph.confidence import get_confidence_level

# ═══════════════════════════════════════════════════════════════════════════════
# Confidence thresholds for test_coverage_signal
# ═══════════════════════════════════════════════════════════════════════════════

#: tested_by edge confidence >= this value is considered "high confidence"
TESTED_BY_HIGH_CONFIDENCE_THRESHOLD: float = 0.75

#: tested_by edge confidence below this threshold but > 0 is "low confidence"
#: (edges with exactly 0 or missing confidence are "unknown confidence")

# ═══════════════════════════════════════════════════════════════════════════════
# Test file detection patterns (path/name heuristics, language-aware)
# ═══════════════════════════════════════════════════════════════════════════════

# Directory patterns that indicate test directories
_TEST_DIR_PATTERNS: list[str] = [
    "tests",
    "test",
    "__tests__",
    "spec",
    "__spec__",
    "testing",
    "testutils",
]

# Filename patterns compiled as regex for each language
# Each entry is (regex, language_id) where regex matches the filename (not path)
_TEST_FILE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Python
    (re.compile(r"^test_.*\.py$"), "python"),
    (re.compile(r".*_test\.py$"), "python"),
    # TypeScript / JavaScript
    (re.compile(r".*\.test\.(ts|tsx|js|jsx|mjs|cjs)$"), "typescript"),
    (re.compile(r".*\.spec\.(ts|tsx|js|jsx|mjs|cjs)$"), "typescript"),
    # Java
    (re.compile(r".*Test(s)?\.java$"), "java"),
    (re.compile(r".*IT(s)?\.java$"), "java"),  # integration tests
    # Go
    (re.compile(r".*_test\.go$"), "go"),
    # C# / .NET
    (re.compile(r".*Test(s)?\.cs$"), "csharp"),
    # Ruby
    (re.compile(r".*_test\.rb$"), "ruby"),
    (re.compile(r".*_spec\.rb$"), "ruby"),
    # Rust
    (re.compile(r".*_test\.rs$"), "rust"),
    # Swift
    (re.compile(r".*Test(s)?\.swift$"), "swift"),
    # Kotlin
    (re.compile(r".*Test(s)?\.kt$"), "kotlin"),
    # PHP
    (re.compile(r".*Test\.php$"), "php"),
]

# Directories to skip when scanning for test files
_EXCLUDE_DIRS: set[str] = {
    ".git", "venv", ".venv", "node_modules",
    "dist", "build", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".codegraph", ".next", ".nuxt", "target", "bin", "obj",
    ".tox", ".eggs", ".egg-info",
}

# Source file extensions recognized across supported languages.
# Files in test directories must match one of these to be counted.
_SOURCE_EXTENSIONS: set[str] = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".java", ".go", ".cs", ".rb", ".rs", ".swift", ".kt",
    ".php", ".c", ".cpp", ".h", ".hpp", ".scala",
}


def _is_test_directory(part: str) -> bool:
    """Check if a directory name matches a test directory pattern."""
    part_lower = part.lower()
    for pattern in _TEST_DIR_PATTERNS:
        if part_lower == pattern or part_lower.startswith(pattern):
            return True
    return False


def _match_test_filename(filename: str) -> str | None:
    """Check if *filename* matches any test file pattern.

    Returns the language_id if matched, or None.
    """
    for pattern, lang_id in _TEST_FILE_PATTERNS:
        if pattern.match(filename):
            return lang_id
    return None


def detect_test_files(project_root: str | Path) -> dict[str, Any]:
    """Scan the filesystem for test files using path/name heuristics.

    This is independent of the CodeGraph index — it finds test files even if
    they were never indexed or have no ``tested_by`` edges.

    Args:
        project_root: The project's root directory.

    Returns:
        A dict with:
        * ``count``: number of test files detected
        * ``sample_files``: up to 5 relative paths of detected test files
        * ``patterns_used``: which directory patterns matched
        * ``languages``: language breakdown of detected test files
    """
    root = Path(project_root)
    if not root.exists() or not root.is_dir():
        return {
            "count": 0,
            "sample_files": [],
            "patterns_used": [],
            "languages": {},
        }

    detected: list[str] = []  # relative paths
    langs: dict[str, int] = {}
    dirs_matched: set[str] = set()

    try:
        for path in root.rglob("*"):
            if not path.is_file():
                continue

            parts = path.relative_to(root).parts
            # Skip excluded directories
            skip = False
            in_test_dir = False
            for part in parts[:-1]:  # check parent dirs
                part_lower = part.lower()
                if part_lower in _EXCLUDE_DIRS or part_lower.startswith("."):
                    skip = True
                    break
                if _is_test_directory(part):
                    in_test_dir = True
                    dirs_matched.add(part)

            if skip:
                continue

            filename = path.name
            lang_match = _match_test_filename(filename)

            # Count only if:
            # 1. Filename matches a test-file pattern (e.g., test_*.py), OR
            # 2. File is inside a test directory AND has a recognized source extension
            if lang_match is not None:
                rel = str(path.relative_to(root)).replace("\\", "/")
                detected.append(rel)
                langs[lang_match] = langs.get(lang_match, 0) + 1
            elif in_test_dir:
                ext = path.suffix.lower()
                if ext in _SOURCE_EXTENSIONS:
                    rel = str(path.relative_to(root)).replace("\\", "/")
                    detected.append(rel)
                    langs["unknown"] = langs.get("unknown", 0) + 1

    except (OSError, PermissionError):
        pass

    # Sort for deterministic output
    detected.sort()

    return {
        "count": len(detected),
        "sample_files": detected[:5],
        "patterns_used": sorted(dirs_matched),
        "languages": langs,
    }


def is_test_file_path(file_path: str) -> bool:
    """Check whether *file_path* looks like a test file.

    Uses the same directory and filename patterns as ``detect_test_files()``
    but operates on a single path string — no filesystem scanning.

    Returns True if the path is in a test directory or matches a
    test-file naming convention.
    """
    normalized = file_path.replace("\\", "/")
    parts = normalized.split("/")
    filename = parts[-1] if parts else ""

    # Check directory patterns (any parent is a test directory)
    for part in parts[:-1]:
        if _is_test_directory(part):
            return True

    # Check filename patterns
    if _match_test_filename(filename) is not None:
        return True

    return False


def compute_test_coverage_signal(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Compute a structured test coverage signal.

    Distinguishes between "no test files exist", "test files exist but
    aren't linked", "low-confidence links", and "high-confidence links".

    Args:
        nodes: All graph nodes.
        edges: All graph edges.
        project_root: Project root for filesystem test detection.
                      If None, only indexed nodes are used.

    Returns:
        A structured dict with ``status``, confidence breakdowns, message,
        warnings, and backward-compatible ``test_files`` / ``tested_symbols``
        counts.
    """
    # ── From index: test nodes ──────────────────────────────────────────
    test_nodes = [n for n in nodes if n.type == NodeType.test]
    test_file_paths: set[str] = {n.file_path for n in test_nodes}

    # ── From index: tested_by edges ────────────────────────────────────
    tested_by_edges = [e for e in edges if e.type == EdgeType.tested_by]
    tested_symbols: set[str] = {e.source for e in tested_by_edges}

    # Confidence breakdown of tested_by edges
    high_conf: set[str] = set()
    low_conf: set[str] = set()
    unknown_conf: set[str] = set()

    for e in tested_by_edges:
        conf = e.confidence
        src = e.source
        if conf <= 0:
            unknown_conf.add(src)
        elif conf >= TESTED_BY_HIGH_CONFIDENCE_THRESHOLD:
            high_conf.add(src)
        else:
            low_conf.add(src)

    # ── Filesystem test detection (if project_root provided) ───────────
    fs_detection: dict[str, Any] | None = None
    if project_root is not None:
        fs_detection = detect_test_files(project_root)
        fs_count = fs_detection["count"]
    else:
        fs_count = 0

    # ── Determine effective test file count ────────────────────────────
    # Use the larger of indexed test files vs filesystem detection
    indexed_test_file_count = len(test_file_paths)
    effective_test_file_count = max(indexed_test_file_count, fs_count)

    # ── Determine status ───────────────────────────────────────────────
    status: str
    confidence: str
    message: str
    warnings: list[str] = []

    total_tested = len(tested_symbols)  # unique production symbols with tests
    total_tested_by_edges = len(tested_by_edges)  # total tested_by edge count
    high_count = len(high_conf)
    low_count = len(low_conf)
    unknown_count = len(unknown_conf)

    # Estimate untested symbols (production symbols that could be tested)
    prod_nodes = [
        n for n in nodes
        if n.type in (
            NodeType.function, NodeType.method, NodeType.class_,
            NodeType.module, NodeType.controller, NodeType.service,
            NodeType.component, NodeType.route,
        )
    ]
    untested_estimate = max(0, len(prod_nodes) - total_tested)

    if effective_test_file_count == 0:
        # Case A: No test files detected anywhere
        status = "unknown"
        confidence = "unknown"
        message = (
            "No test files were detected by path/name heuristics "
            "in this repository."
        )
    elif total_tested == 0:
        # Case B: Test files detected but no tested_by edges
        status = "incomplete"
        confidence = "unknown"
        message = (
            "Test files were detected, but no tested_by edges "
            "link them to production symbols. CodeGraph cannot "
            "confidently map tests to the code they cover. "
            "Use CodeGraph for navigation, but verify coverage "
            "by reading relevant tests directly."
        )
        if indexed_test_file_count == 0 and fs_count > 0:
            warnings.append(
                f"{fs_count} test file(s) found on disk but none are "
                f"indexed as test nodes. The index may be stale or test "
                f"files may not have been parsed."
            )
        elif indexed_test_file_count > 0:
            warnings.append(
                f"{indexed_test_file_count} indexed test file(s) exist "
                f"but no tested_by edges were created. This may indicate "
                f"that the test relationship builder did not link them."
            )
    elif high_count == 0 and total_tested > 0:
        # Case C: tested_by edges exist but are low/unknown confidence
        status = "low_confidence"
        confidence = get_confidence_level(
            sum(e.confidence for e in tested_by_edges if e.confidence) / total_tested
            if total_tested > 0 else 0
        )
        message = (
            "Test coverage links exist but are mostly low-confidence "
            "heuristics. CodeGraph can suggest which tests might be "
            "related, but verify each link before relying on it."
        )
        warnings.append(
            f"{total_tested} production symbol(s) linked to tests, "
            f"but {low_count + unknown_count} link(s) are low or unknown "
            f"confidence."
        )
    elif high_count > 0:
        # Case D: At least some high-confidence tested_by edges
        if high_count >= total_tested * 0.5:
            status = "ok"
            confidence = "high"
            message = (
                "Test coverage signal is usable. The majority of "
                "tested_by edges have high confidence."
            )
        else:
            status = "low_confidence"
            confidence = "medium"
            message = (
                "Some high-confidence test links exist, but many are "
                "low-confidence. Coverage signal is partially usable."
            )
        if low_count > 0 or unknown_count > 0:
            warnings.append(
                f"{high_count} high-confidence tested symbol(s), "
                f"{low_count} low-confidence, {unknown_count} unknown. "
                f"Low-confidence links may be incorrect."
            )
    else:
        status = "unknown"
        confidence = "unknown"
        message = (
            "Test coverage signal could not be determined. "
            "Use CodeGraph for navigation, but verify test coverage "
            "independently."
        )

    # ── Build result ──────────────────────────────────────────────────
    result: dict[str, Any] = {
        "status": status,
        "confidence": confidence,
        "message": message,
        "warnings": warnings,
        # New structured fields
        "test_files_detected": effective_test_file_count,
        "tested_symbols_high_confidence": high_count,
        "tested_symbols_low_confidence": low_count,
        "tested_symbols_unknown_confidence": unknown_count,
        "untested_symbols_estimate": untested_estimate,
        "tested_by_edges": total_tested_by_edges,
        # Backward-compatible fields
        "test_files": effective_test_file_count,
        "tested_symbols": total_tested,
    }

    # Include filesystem detection details when available
    if fs_detection is not None:
        result["test_file_detection"] = {
            "method": "filesystem_heuristic",
            "count": fs_detection["count"],
            "sample_files": fs_detection["sample_files"],
            "patterns_used": fs_detection["patterns_used"],
            "languages": fs_detection["languages"],
        }
        # If fs found files but index has none, add a specific note
        if fs_count > 0 and indexed_test_file_count == 0:
            result["test_file_detection"]["note"] = (
                "Test files found on disk but not in the CodeGraph index. "
                "Re-index to include them."
            )

    return result
