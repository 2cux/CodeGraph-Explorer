"""Graph data models — Node, Edge, and top-level schema.

Matches PRD Section 12 (Graph Schema) specification.
"""

from enum import Enum
from pydantic import BaseModel, Field
from typing import Any


# ── Enums ────────────────────────────────────────────────────────────


class NodeType(str, Enum):
    repository = "repository"
    file = "file"
    module = "module"
    class_ = "class"
    function = "function"
    method = "method"
    import_ = "import"
    external_symbol = "external_symbol"
    test = "test"


class EdgeType(str, Enum):
    contains = "contains"
    defined_in = "defined_in"
    imports = "imports"
    calls = "calls"
    inherits = "inherits"
    references = "references"
    tested_by = "tested_by"


class Resolution(str, Enum):
    """Confidence resolution strategy — PRD §12.8."""

    exact_ast_match = "exact_ast_match"
    same_file_exact = "same_file_exact"
    import_resolved = "import_resolved"
    class_method_resolved = "class_method_resolved"
    type_hint_resolved = "type_hint_resolved"
    test_name_heuristic = "test_name_heuristic"
    attribute_guess = "attribute_guess"
    external_symbol = "external_symbol"
    unresolved = "unresolved"


# ── Location / Metadata models ──────────────────────────────────────


class Location(BaseModel):
    """Source code location — PRD §12.3."""

    line_start: int
    line_end: int
    column_start: int | None = None
    column_end: int | None = None


class EdgeLocation(BaseModel):
    """Source location attached to an edge — PRD §12.6."""

    file_path: str
    line_start: int
    line_end: int


class EdgeMetadata(BaseModel):
    """Metadata attached to a calls/references edge — PRD §12.6, §12.8."""

    call_expr: str | None = None
    resolution: Resolution
    is_dynamic: bool = False


# ── Repo model ──────────────────────────────────────────────────────


class RepoInfo(BaseModel):
    """Repository metadata — PRD §12.2."""

    repo_id: str
    name: str
    root_path: str
    languages: list[str] = ["python"]
    indexed_at: str = ""
    commit_hash: str = ""
    indexer_version: str = "1.0.0"
    file_count: int = 0
    symbol_count: int = 0


# ── Node / Edge ─────────────────────────────────────────────────────


class GraphNode(BaseModel):
    """A node in the code graph — PRD §12.3."""

    id: str
    type: NodeType
    name: str
    qualified_name: str = ""
    display_name: str = ""
    file_path: str = ""
    module: str = ""
    language: str = "python"
    location: Location | None = None
    signature: str | None = None
    docstring: str | None = None
    code_preview: str | None = None
    visibility: str = "public"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """A directed edge in the code graph — PRD §12.6."""

    id: str = ""
    type: EdgeType
    source: str
    target: str
    confidence: float = 1.0
    source_location: EdgeLocation | None = None
    metadata: EdgeMetadata | None = None


# ── Top-level graph ─────────────────────────────────────────────────


class CodeGraph(BaseModel):
    """Top-level graph container — PRD §12.1."""

    schema_version: str = "1.0.0"
    repo: RepoInfo = Field(default_factory=RepoInfo)
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    indexes: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
