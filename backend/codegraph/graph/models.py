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
    """Confidence resolution strategy — PRD §12.8.

    All confidence values are centralized in ``codegraph.graph.confidence``.
    """

    # ── Structural / exact ──────────────────────────────────────────
    exact_ast_match = "exact_ast_match"

    # ── Call resolution ─────────────────────────────────────────────
    same_file_exact = "same_file_exact"
    self_method_resolved = "self_method_resolved"
    imported_function_exact = "imported_function_exact"
    imported_function_alias = "imported_function_alias"
    imported_module_attribute = "imported_module_attribute"
    relative_import_resolved = "relative_import_resolved"
    import_resolved = "import_resolved"
    class_method_resolved = "class_method_resolved"
    parameter_type_hint_resolved = "parameter_type_hint_resolved"
    local_instance_resolved = "local_instance_resolved"
    module_instance_resolved = "module_instance_resolved"
    constructor_call_resolved = "constructor_call_resolved"
    self_attribute_instance_resolved = "self_attribute_instance_resolved"
    same_module_fallback = "same_module_fallback"
    type_hint_resolved = "type_hint_resolved"

    # ── TS/JS import resolution ─────────────────────────────────────
    imported_symbol_exact = "imported_symbol_exact"
    imported_alias_exact = "imported_alias_exact"
    default_import_exact = "default_import_exact"
    namespace_import_exact = "namespace_import_exact"
    relative_import_exact = "relative_import_exact"
    barrel_export_resolved = "barrel_export_resolved"
    this_method_exact = "this_method_exact"
    class_method_exact = "class_method_exact"
    require_exact = "require_exact"
    module_exports_exact = "module_exports_exact"

    # ── TS/JS possible / low-confidence ────────────────────────────
    object_method_unknown = "object_method_unknown"
    dynamic_property_access = "dynamic_property_access"
    callback_candidate = "callback_candidate"

    # ── TS/JS unresolved / external ─────────────────────────────────
    package_external = "package_external"
    dynamic_import = "dynamic_import"
    require_unknown = "require_unknown"
    computed_property = "computed_property"
    any_unknown = "any_unknown"

    # ── Route / entry-point detection ───────────────────────────────
    fastapi_route_decorator = "fastapi_route_decorator"
    flask_route_decorator = "flask_route_decorator"
    django_view_heuristic = "django_view_heuristic"
    framework_route_resolved = "framework_route_resolved"

    # ── Test discovery ──────────────────────────────────────────────
    direct_test_call = "direct_test_call"
    test_import_match = "test_import_match"
    test_name_heuristic = "test_name_heuristic"
    test_file_heuristic = "test_file_heuristic"
    suggested_test = "suggested_test"

    # ── Possible / low-confidence candidates ────────────────────────
    name_match_candidate = "name_match_candidate"
    filename_heuristic = "filename_heuristic"
    docstring_reference = "docstring_reference"

    # ── Unresolved / external / dynamic ─────────────────────────────
    dynamic_getattr = "dynamic_getattr"
    reflection_call = "reflection_call"
    unknown_external = "unknown_external"
    decorator_unknown = "decorator_unknown"
    import_not_found = "import_not_found"

    # ── Model / config / persistence detection ──────────────────────
    pydantic_model_detected = "pydantic_model_detected"
    dataclass_model_detected = "dataclass_model_detected"
    sqlalchemy_model_detected = "sqlalchemy_model_detected"
    config_class_detected = "config_class_detected"
    config_constant_detected = "config_constant_detected"
    repository_name_match = "repository_name_match"
    store_name_match = "store_name_match"
    model_field_match = "model_field_match"
    config_field_match = "config_field_match"
    persistence_name_match = "persistence_name_match"

    # ── Ranking / context scoring ───────────────────────────────────
    symbol_name_match = "symbol_name_match"
    file_path_match = "file_path_match"
    route_path_match = "route_path_match"
    tag_match = "tag_match"
    field_name_match = "field_name_match"
    call_graph_neighbor = "call_graph_neighbor"
    impact_neighbor = "impact_neighbor"

    # ── Fallbacks ───────────────────────────────────────────────────
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
    reason: str | None = None
    evidence: dict[str, Any] | None = None
    provenance: str | None = None
    """How the edge was discovered — one of ``Provenance`` enum values:
    ``ast``, ``import_resolver``, ``type_resolver``, ``framework_resolver``,
    ``heuristic``, ``external_index``."""


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
    language_id: str = "python"
    """Language identifier (e.g. ``python``, ``typescript``).
    Added in Phase 1 multi-language refactoring."""
    framework_id: str | None = None
    """Framework identifier (e.g. ``fastapi``, ``django``) or ``None``."""
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


# ── Index metadata (incremental indexing) ────────────────────────────


class FileEntry(BaseModel):
    """Per-file metadata stored in .codegraph/metadata.json."""

    path: str
    fingerprint: str
    indexed_at: str = ""


class IndexMetadata(BaseModel):
    """Index metadata for incremental update and stale detection."""

    schema_version: str = "1.0.0"
    indexer_version: str = "1.0.0"
    root_path: str = ""
    indexed_at: str = ""
    file_count: int = 0
    symbol_count: int = 0
    edge_count: int = 0
    files: list[FileEntry] = Field(default_factory=list)


# ── Top-level graph ─────────────────────────────────────────────────


class CodeGraph(BaseModel):
    """Top-level graph container — PRD §12.1."""

    schema_version: str = "1.0.0"
    repo: RepoInfo = Field(default_factory=RepoInfo)
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    indexes: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
