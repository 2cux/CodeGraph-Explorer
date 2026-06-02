"""Language extractor interface — unified extraction contract.

Each language implements a :class:`LanguageExtractor` that takes a file
and returns an :class:`ExtractorResult` containing symbols, imports,
exports, calls, references, routes, tests, configs, and diagnostics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from typing import Any

from codegraph.graph.models import GraphNode


# ── Structured sub-results ─────────────────────────────────────────────

class ImportInfo(BaseModel):
    """A single import statement resolved to its target."""
    local_name: str
    module_path: str
    imported_name: str | None = None  # None = module import
    is_external: bool = False
    line: int = 0


class ExportInfo(BaseModel):
    """A symbol exported from this file."""
    name: str
    node_id: str
    is_default: bool = False


class CallEdge(BaseModel):
    """An intra-file or pending cross-file call (unresolved at extract time)."""
    source_node_id: str
    target_expression: str           # e.g. "module.func" or "func"
    target_qualified_name: str | None = None  # resolved qualified name
    line: int = 0
    call_expr: str | None = None
    is_dynamic: bool = False


class RefEdge(BaseModel):
    """A reference from one symbol to another (non-call)."""
    source_node_id: str
    target_expression: str
    target_qualified_name: str | None = None
    line: int = 0


class RouteInfo(BaseModel):
    """A detected HTTP route / endpoint."""
    framework: str
    method: str
    path: str
    handler_node_id: str


class TestInfo(BaseModel):
    """A detected test symbol."""
    node_id: str
    test_type: str = "function"  # "function", "method", "class"


class ConfigInfo(BaseModel):
    """A detected configuration symbol or constant."""
    node_id: str
    config_type: str = "class"   # "class", "constant", "field"


class Diagnostic(BaseModel):
    """An extraction warning or error."""
    level: str = "warning"       # "warning" | "error"
    message: str
    file_path: str = ""
    line: int | None = None


# ── Extractor result ────────────────────────────────────────────────────

class ExtractorResult(BaseModel):
    """Output of a single-file extraction.

    All non-symbol fields are structured sub-results that the
    :class:`Resolver` uses for cross-file edge construction.
    """

    language_id: str
    file_path: str
    symbols: list[GraphNode] = Field(default_factory=list)
    imports: list[ImportInfo] = Field(default_factory=list)
    exports: list[ExportInfo] = Field(default_factory=list)
    calls: list[CallEdge] = Field(default_factory=list)
    references: list[RefEdge] = Field(default_factory=list)
    routes: list[RouteInfo] = Field(default_factory=list)
    tests: list[TestInfo] = Field(default_factory=list)
    configs: list[ConfigInfo] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


# ── Extractor interface ─────────────────────────────────────────────────

class LanguageExtractor(ABC):
    """Abstract base class for per-language file extractors.

    Each implementation extracts code facts from a single source file
    and returns an :class:`ExtractorResult`. The result is language-agnostic;
    the resolver layer handles cross-file relationship construction.
    """

    @abstractmethod
    def extract(self, file_path: str, content: str | None = None,
                project_root: str | None = None,
                config: dict[str, Any] | None = None) -> ExtractorResult:
        """Extract symbols, calls, imports, etc. from a single file.

        Args:
            file_path: Absolute or project-relative file path.
            content: File source text. If ``None``, the extractor reads
                     *file_path* from disk.
            project_root: Project root directory. Used for relative path
                          computation and module name derivation.
            config: Optional language-specific extraction config.

        Returns:
            :class:`ExtractorResult` populated with all discovered facts.
        """
        ...
