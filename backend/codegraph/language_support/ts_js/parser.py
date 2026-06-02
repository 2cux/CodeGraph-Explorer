"""Tree-sitter parser adapter for TypeScript / JavaScript.

Wraps tree-sitter + tree-sitter-languages into a simple interface
used by TypeScriptExtractor and JavaScriptExtractor.

Design:
- tree-sitter is an *optional* dependency.  When it is not available the
  adapter reports a ``"parser_unavailable"`` diagnostic and returns an
  empty tree — callers must handle the graceful-degrade path.
- Parser errors (malformed syntax, unsupported constructs) are captured
  as diagnostics rather than raising exceptions, so a single broken file
  never fails the whole index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from codegraph.language_support.extractor import Diagnostic


@dataclass
class ParseResult:
    """Output of ``TreeSitterParser.parse()``."""

    language: str
    content: str
    tree: Any | None = None          # tree-sitter Tree
    root_node: Any | None = None      # tree-sitter Node (root)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.tree is not None and self.root_node is not None


class TreeSitterParser:
    """Thin adapter over tree-sitter-languages for TS/JS parsing.

    Usage::

        adapter = TreeSitterParser()
        result = adapter.parse("const x = 1;", language="typescript")
        if result.ok:
            # walk result.root_node.children ...
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._available: bool | None = None
        self._parsers: dict[str, Any] = {}

    @property
    def available(self) -> bool:
        """True when tree-sitter + tree-sitter-languages can be imported."""
        if self._available is None:
            try:
                import tree_sitter_languages  # noqa: F401
                self._available = True
            except ImportError:
                self._available = False
        return self._available

    def parse(self, content: str, language: str, file_path: str = "") -> ParseResult:
        """Parse *content* as *language* (``"typescript"`` or ``"javascript"``).

        Returns a ``ParseResult`` that is ``ok`` on success.  On failure
        (missing dependency, syntax error, …) the result carries one or
        more diagnostics.
        """
        diags: list[Diagnostic] = []

        if not self.available:
            diags.append(Diagnostic(
                level="error",
                message="tree-sitter not available; install with: pip install codegraph[ts]",
                file_path=file_path,
                line=None,
            ))
            return ParseResult(
                language=language, content=content, diagnostics=diags,
            )

        try:
            parser = self._get_parser(language)
            tree = parser.parse(bytes(content, "utf-8"))
            root = tree.root_node

            # Collect syntax errors from the CST
            if root.has_error:
                for child in root.children:
                    if child.type == "ERROR":
                        diags.append(Diagnostic(
                            level="warning",
                            message=f"Parse error near line {child.start_point[0] + 1}",
                            file_path=file_path,
                            line=child.start_point[0] + 1,
                        ))

            return ParseResult(
                language=language,
                content=content,
                tree=tree,
                root_node=root if not root.has_error else root,
                diagnostics=diags,
            )
        except Exception as exc:
            diags.append(Diagnostic(
                level="error",
                message=f"Parser error: {exc}",
                file_path=file_path,
                line=None,
            ))
            return ParseResult(
                language=language, content=content, diagnostics=diags,
            )

    def query(self, tree: Any, pattern: str) -> list[dict[str, Any]]:
        """Execute a tree-sitter query and return named captures.

        Each result dict maps capture name → ``(node, text)`` tuple.
        """
        if not self.available:
            return []
        try:
            lang = tree.language if hasattr(tree, "language") else None
            if lang is None:
                return []
            query_obj = lang.query(pattern)
            captures = query_obj.captures(tree.root_node)
            results: list[dict[str, Any]] = []
            # captures is a dict {capture_name: list[nodes]}
            for name, nodes in captures.items():
                for node in nodes:
                    results.append({
                        "name": name,
                        "node": node,
                        "text": node.text.decode("utf-8") if hasattr(node, "text") else "",
                        "start_line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                    })
            return results
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_parser(self, language: str) -> Any:
        if language not in self._parsers:
            import tree_sitter_languages as tsl
            self._parsers[language] = tsl.get_parser(language)
        return self._parsers[language]


# Singleton for reuse across the index run
_parser_instance: TreeSitterParser | None = None


def get_parser() -> TreeSitterParser:
    global _parser_instance
    if _parser_instance is None:
        _parser_instance = TreeSitterParser()
    return _parser_instance
