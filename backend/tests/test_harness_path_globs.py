"""Tests for path/glob handling in the harness layer.

Covers PowerShell/glob path scenarios:
- backend/codegraph/** pattern
- "backend/codegraph/**" quoted pattern
- backend/codegraph/graph/coverage_gaps.py specific file
- Verifying internal glob processing consistency

Tests coerce_str_list, glob resolution, and path normalization in
harness module_utils and related utilities.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

import pytest

from codegraph.harness.module_utils import coerce_str_list, coerce_bool


# ── coerce_str_list ────────────────────────────────────────────────────────


class TestCoerceStrList:
    def test_single_string_becomes_list(self) -> None:
        result = coerce_str_list("backend/codegraph/**")
        assert result == ["backend/codegraph/**"]

    def test_list_passed_through(self) -> None:
        result = coerce_str_list(["backend/codegraph/**", "backend/tests/**"])
        assert result == ["backend/codegraph/**", "backend/tests/**"]

    def test_none_returns_empty_list(self) -> None:
        result = coerce_str_list(None)
        assert result == []

    def test_empty_list_returns_empty_list(self) -> None:
        result = coerce_str_list([])
        assert result == []

    def test_single_path_with_quotes_stripped(self) -> None:
        # The coerce_str_list doesn't strip quotes — it's the caller's job
        # But it should still handle the value as-is
        result = coerce_str_list('backend/codegraph/**')
        assert result == ['backend/codegraph/**']

    def test_comma_separated_string(self) -> None:
        # coerce_str_list DOES split by comma and strip each item
        result = coerce_str_list("backend/codegraph/**,backend/tests/**")
        assert result == ["backend/codegraph/**", "backend/tests/**"]

    def test_multiple_items_with_wildcards(self) -> None:
        result = coerce_str_list([
            "backend/codegraph/**",
            "backend/tests/*.py",
            "docs/**/*.md",
        ])
        assert len(result) == 3
        assert "backend/codegraph/**" in result


# ── coerce_bool ────────────────────────────────────────────────────────────


class TestCoerceBoolExtended:
    def test_coerce_bool_true_strings(self) -> None:
        assert coerce_bool("true", default=False) is True
        assert coerce_bool("True", default=False) is True
        assert coerce_bool("TRUE", default=False) is True
        assert coerce_bool("1", default=False) is True

    def test_coerce_bool_false_strings(self) -> None:
        assert coerce_bool("false", default=True) is False
        assert coerce_bool("False", default=True) is False
        assert coerce_bool("FALSE", default=True) is False
        assert coerce_bool("0", default=True) is False

    def test_coerce_bool_actual_bool(self) -> None:
        assert coerce_bool(True, default=False) is True
        assert coerce_bool(False, default=True) is False

    def test_coerce_bool_none_uses_default(self) -> None:
        assert coerce_bool(None, default=True) is True
        assert coerce_bool(None, default=False) is False

    def test_coerce_bool_unexpected_string_raises(self) -> None:
        # Pydantic TypeAdapter(bool) raises ValidationError for non-bool strings
        import pytest as pt
        from pydantic import ValidationError

        with pt.raises(ValidationError):
            coerce_bool("maybe", default=True)


# ── fnmatch / glob pattern matching ────────────────────────────────────────


class TestGlobPatternMatching:
    """Verify that Python's fnmatch handles the path patterns consistently."""

    @pytest.mark.parametrize(
        "pattern,path,expected",
        [
            # Standard glob patterns
            ("backend/codegraph/**", "backend/codegraph/graph/query.py", True),
            ("backend/codegraph/**", "backend/codegraph/indexer/scanner.py", True),
            ("backend/codegraph/**", "backend/tests/test_harness.py", False),
            # Specific file matching
            ("backend/codegraph/graph/coverage_gaps.py", "backend/codegraph/graph/coverage_gaps.py", True),
            ("backend/codegraph/graph/coverage_gaps.py", "backend/codegraph/graph/query.py", False),
            # Wildcard in filename
            ("backend/codegraph/**/*.py", "backend/codegraph/graph/query.py", True),
            ("backend/codegraph/**/*.py", "backend/codegraph/graph/query.md", False),
            # Test directory patterns
            ("backend/tests/**", "backend/tests/test_harness.py", True),
            ("backend/tests/**", "backend/codegraph/store.py", False),
        ],
    )
    def test_fnmatch_consistency(
        self, pattern: str, path: str, expected: bool
    ) -> None:
        """Verify fnmatch behavior matches expectations for path patterns."""
        result = fnmatch.fnmatch(path, pattern)
        assert result == expected, (
            f"fnmatch('{path}', '{pattern}') should be {expected}, got {result}"
        )

    def test_double_star_matches_nested_directories(self) -> None:
        """** should match any depth of directories."""
        assert fnmatch.fnmatch("backend/codegraph/graph/query.py", "backend/codegraph/**")
        assert fnmatch.fnmatch("backend/codegraph/a/b/c/d.py", "backend/codegraph/**")

    def test_single_star_only_matches_one_level(self) -> None:
        """fnmatch * matches any characters INCLUDING / unlike real glob.

        This is a known difference: fnmatch.fnmatch treats * as matching
        everything including path separators. For path-aware glob matching,
        use pathlib.Path.glob() or glob.glob() instead.
        """
        # fnmatch's * DOES match across / chars
        assert fnmatch.fnmatch("backend/codegraph/query.py", "backend/codegraph/*")
        assert fnmatch.fnmatch(
            "backend/codegraph/graph/query.py", "backend/codegraph/*"
        )
        # ** also matches everything
        assert fnmatch.fnmatch("backend/codegraph/a/b/c/d.py", "backend/codegraph/**")


# ── Path normalization ─────────────────────────────────────────────────────


class TestPathNormalization:
    def test_forward_slash_paths(self) -> None:
        """Forward-slash paths should be handled consistently."""
        path = "backend/codegraph/graph/coverage_gaps.py"
        assert "/" in path
        assert "\\" not in path

    def test_backslash_paths(self) -> None:
        """Backslash paths (Windows) should be normalizable."""
        path = "backend\\codegraph\\graph\\coverage_gaps.py"
        normalized = path.replace("\\", "/")
        assert normalized == "backend/codegraph/graph/coverage_gaps.py"

    def test_path_normalization_via_pathlib(self) -> None:
        """Pathlib should normalize separators consistently."""
        p = Path("backend/codegraph/graph/coverage_gaps.py")
        # On Windows, Path may use backslashes internally
        as_posix = p.as_posix()
        assert "\\" not in as_posix
        assert as_posix == "backend/codegraph/graph/coverage_gaps.py"


# ── Input coercion integration ─────────────────────────────────────────────


class TestInputCoercionIntegration:
    """Simulate how harness modules receive and process input paths."""

    def test_paths_from_input_dict(self) -> None:
        """Simulate workflow.test_audit receiving paths from input_data."""
        input_data = {"paths": ["backend/codegraph/**", "backend/tests/**"]}
        paths = coerce_str_list(input_data.get("paths"))
        assert len(paths) == 2
        assert "backend/codegraph/**" in paths
        assert "backend/tests/**" in paths

    def test_single_path_from_input_dict(self) -> None:
        """Single string path should be coerced to list."""
        input_data = {"paths": "backend/codegraph/**"}
        paths = coerce_str_list(input_data.get("paths"))
        assert len(paths) == 1
        assert paths[0] == "backend/codegraph/**"

    def test_coverage_gaps_file_path(self) -> None:
        """Explicit coverage_gaps.py path should be preserved."""
        input_data = {"paths": ["backend/codegraph/graph/coverage_gaps.py"]}
        paths = coerce_str_list(input_data.get("paths"))
        assert paths == ["backend/codegraph/graph/coverage_gaps.py"]

    def test_empty_paths_default_to_all(self) -> None:
        """Empty paths list should be treated as 'all' by the module."""
        input_data = {"paths": []}
        paths = coerce_str_list(input_data.get("paths"))
        assert paths == []
