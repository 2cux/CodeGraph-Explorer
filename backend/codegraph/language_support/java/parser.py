"""Tree-sitter parser adapter for Java.

Wraps tree-sitter + tree-sitter-languages for Java parsing.
Follows the same pattern as the TS/JS parser adapter.

Tree-sitter is an *optional* dependency. When unavailable the adapter
returns an empty tree with a "parser_unavailable" diagnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from codegraph.language_support.extractor import Diagnostic


@dataclass
class ParseResult:
    """Output of ``JavaParser.parse()``."""

    language: str
    content: str
    tree: Any | None = None
    root_node: Any | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.tree is not None and self.root_node is not None


class JavaParser:
    """Thin adapter over tree-sitter-languages for Java parsing."""

    def __init__(self) -> None:
        self._available: bool | None = None
        self._parser: Any | None = None

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

    def parse(self, content: str, file_path: str = "") -> ParseResult:
        """Parse *content* as Java.

        Returns a ``ParseResult`` that is ``ok`` on success.
        """
        diags: list[Diagnostic] = []

        if not self.available:
            diags.append(Diagnostic(
                level="error",
                message="tree-sitter not available; install with: pip install tree-sitter-languages",
                file_path=file_path,
                line=None,
            ))
            return ParseResult(
                language="java", content=content, diagnostics=diags,
            )

        try:
            parser = self._get_parser()
            tree = parser.parse(bytes(content, "utf-8"))
            root = tree.root_node

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
                language="java",
                content=content,
                tree=tree,
                root_node=root,
                diagnostics=diags,
            )
        except Exception as exc:
            diags.append(Diagnostic(
                level="error",
                message=f"Java parser error: {exc}",
                file_path=file_path,
                line=None,
            ))
            return ParseResult(
                language="java", content=content, diagnostics=diags,
            )

    def _get_parser(self) -> Any:
        if self._parser is None:
            import tree_sitter_languages as tsl
            self._parser = tsl.get_parser("java")
        return self._parser


# Singleton for reuse
_parser_instance: JavaParser | None = None


def get_parser() -> JavaParser:
    global _parser_instance
    if _parser_instance is None:
        _parser_instance = JavaParser()
    return _parser_instance
