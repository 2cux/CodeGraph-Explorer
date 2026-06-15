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
    route = "route"
    controller = "controller"
    service = "service"
    component = "component"


class EdgeType(str, Enum):
    contains = "contains"
    defined_in = "defined_in"
    imports = "imports"
    calls = "calls"
    inherits = "inherits"
    references = "references"
    tested_by = "tested_by"
    routes_to = "routes_to"
    depends_on = "depends_on"
    configures = "configures"
    documents = "documents"
    deploys = "deploys"
    defines_schema = "defines_schema"
    migrates = "migrates"
    runs_script = "runs_script"


class DropReason(str, Enum):
    """Why an edge or node was dropped during validation or indexing."""

    missing_source = "missing_source"
    """Edge source node does not exist in the graph."""
    missing_target = "missing_target"
    """Edge target node does not exist in the graph."""
    missing_both = "missing_both"
    """Both source and target nodes are missing."""
    invalid_edge_type = "invalid_edge_type"
    """Edge type string is not in the canonical EdgeType enum and has no alias."""
    alias_mismatch = "alias_mismatch"
    """Edge type was an alias but could not be normalized (legacy; now handled by normalize layer)."""
    path_mismatch = "path_mismatch"
    """Node file_path resolves outside the project root."""
    external_unresolved = "external_unresolved"
    """Unresolved external symbol edge (resolver 'unresolved' tier discarded)."""
    duplicate_edge = "duplicate_edge"
    """Duplicate (source, target, type) triple — first occurrence kept."""
    duplicate_node_id = "duplicate_node_id"
    """Duplicate node ID — first occurrence kept."""
    malformed_edge = "malformed_edge"
    """Edge is missing required fields (source, target, or type)."""
    parser_missing = "parser_missing"
    """No extractor available or extractor raised an exception for a file."""
    framework_unresolved = "framework_unresolved"
    """Resolver possible/unresolved tier edge discarded during merge."""
    schema_mismatch = "schema_mismatch"
    """SQLite schema version does not match the supported version."""


class AutoCorrectReason(str, Enum):
    """Why an edge or node was auto-corrected during validation."""

    missing_edge_id = "missing_edge_id"
    """Edge had no ID — a new one was generated."""
    duplicate_edge_id = "duplicate_edge_id"
    """Duplicate edge ID — regenerated to be unique."""
    confidence_clamped = "confidence_clamped"
    """Confidence value was outside [0, 1] — clamped to valid range."""
    missing_tags = "missing_tags"
    """Node had null tags — set to empty list."""
    missing_reason_code = "missing_reason_code"
    """Edge metadata had null reason — set to empty string."""
    type_alias_corrected = "type_alias_corrected"
    """Non-canonical edge/node type normalized to canonical form (e.g. implements → inherits)."""
    path_normalized = "path_normalized"
    """File path backslashes normalized to forward slashes."""
    symbol_kind_normalized = "symbol_kind_normalized"
    """Non-canonical node type normalized (e.g. func → function, cls → class)."""
    line_range_fixed = "line_range_fixed"
    """Line range was invalid (end < start) — fixed."""
    duplicate_merged = "duplicate_merged"
    """Duplicate (source, target, type) merged — later occurrences dropped."""


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
    express_route_handler = "express_route_handler"
    nextjs_file_route = "nextjs_file_route"
    nestjs_controller_route = "nestjs_controller_route"
    nestjs_injection_resolved = "nestjs_injection_resolved"
    jsx_component_resolved = "jsx_component_resolved"
    inline_handler = "inline_handler"
    event_emitter_heuristic = "event_emitter_heuristic"
    callback_invocation_heuristic = "callback_invocation_heuristic"
    react_event_handler_heuristic = "react_event_handler_heuristic"
    middleware_chain_heuristic = "middleware_chain_heuristic"
    non_code_configuration = "non_code_configuration"
    non_code_documentation = "non_code_documentation"
    non_code_deployment = "non_code_deployment"
    non_code_schema = "non_code_schema"
    non_code_migration = "non_code_migration"
    non_code_script = "non_code_script"

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

    # ── Java resolution ─────────────────────────────────────────────
    imported_class_exact = "imported_class_exact"
    package_local_exact = "package_local_exact"
    static_method_exact = "static_method_exact"
    annotation_resolved = "annotation_resolved"
    overloaded_method_candidate = "overloaded_method_candidate"
    interface_method_candidate = "interface_method_candidate"
    unknown_type_method = "unknown_type_method"
    external_package = "external_package"
    dynamic_proxy = "dynamic_proxy"
    unknown_symbol = "unknown_symbol"
    # ── Spring framework resolution ─────────────────────────────────
    spring_rest_controller = "spring_rest_controller"
    spring_controller = "spring_controller"
    spring_service = "spring_service"
    spring_repository = "spring_repository"
    spring_component = "spring_component"
    spring_route_resolved = "spring_route_resolved"
    spring_di_constructor = "spring_di_constructor"
    spring_di_autowired = "spring_di_autowired"
    spring_bean_candidate = "spring_bean_candidate"
    spring_overloaded_route = "spring_overloaded_route"

    # ── Go confirmed resolution ────────────────────────────────────
    same_package_exact = "same_package_exact"
    package_import_exact = "package_import_exact"
    package_function_exact = "package_function_exact"
    receiver_method_exact = "receiver_method_exact"
    local_function_exact = "local_function_exact"
    struct_method_exact = "struct_method_exact"

    # ── Go possible / low-confidence ───────────────────────────────
    embedded_method_candidate = "embedded_method_candidate"
    unknown_receiver_method = "unknown_receiver_method"

    # ── Go unresolved / external ───────────────────────────────────
    external_module = "external_module"
    dynamic_dispatch = "dynamic_dispatch"
    cgo_external = "cgo_external"
    unknown_receiver = "unknown_receiver"

    # ── Gin framework resolution ───────────────────────────────────
    gin_route_resolved = "gin_route_resolved"
    gin_group_route_resolved = "gin_group_route_resolved"
    gin_middleware_chain = "gin_middleware_chain"
    gin_inline_handler = "gin_inline_handler"

    # ── Hertz framework resolution ─────────────────────────────────
    hertz_route_resolved = "hertz_route_resolved"
    hertz_group_route_resolved = "hertz_group_route_resolved"
    hertz_middleware_chain = "hertz_middleware_chain"
    hertz_inline_handler = "hertz_inline_handler"

    # ── C# confirmed resolution ────────────────────────────────────
    namespace_local_exact = "namespace_local_exact"
    using_namespace_exact = "using_namespace_exact"
    using_alias_exact = "using_alias_exact"
    base_method_exact = "base_method_exact"

    # ── C# possible / low-confidence ───────────────────────────────
    extension_method_candidate = "extension_method_candidate"
    generated_code = "generated_code"

    # ── ASP.NET Core framework ─────────────────────────────────────
    aspnetcore_controller = "aspnetcore_controller"
    aspnetcore_route_attribute = "aspnetcore_route_attribute"
    aspnetcore_minimal_api = "aspnetcore_minimal_api"
    aspnetcore_di_constructor = "aspnetcore_di_constructor"
    aspnetcore_map_group = "aspnetcore_map_group"

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
    support_level: str = "production"
    """Support level from LanguageRegistry: production, beta, experimental, unsupported."""
    location: Location | None = None
    signature: str | None = None
    docstring: str | None = None
    code_preview: str | None = None
    visibility: str = "public"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # ── Enrichment fields (schema 1.1.0) ─────────────────────────────
    summary: str = ""
    """AI-generated summary of the symbol's purpose and behavior."""
    role: str = ""
    """Inferred architectural role (e.g. service, controller, model, config)."""
    responsibilities: list[str] = Field(default_factory=list)
    """List of responsibilities this symbol fulfills."""
    edge_cases: list[str] = Field(default_factory=list)
    """Known edge cases and boundary conditions."""
    test_relevance: str = ""
    """Guidance on what to focus testing on for this symbol."""
    enrichment_confidence: str = ""
    """Confidence of the enrichment analysis: high, medium, or low."""
    enrichment_evidence: list[dict[str, Any]] = Field(default_factory=list)
    """Evidence references: [{file, line_start, line_end}, ...]."""
    enrichment_status: str = ""
    """Enrichment pipeline status: pending, analyzed, skipped, or error."""
    enriched_at: str = ""
    """ISO 8601 timestamp of when enrichment was imported."""


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


# ── Validation / Health models ────────────────────────────────────────


class DropEntry(BaseModel):
    """A single dropped edge or node with full classification."""

    reason: DropReason
    category: str = "dropped"
    message: str
    edge_id: str | None = None
    source: str | None = None
    target: str | None = None
    edge_type: str | None = None
    node_id: str | None = None
    node_name: str | None = None
    file_path: str | None = None
    language_id: str | None = None
    resolution: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AutoCorrectEntry(BaseModel):
    """A single auto-correction applied to an edge or node."""

    reason: AutoCorrectReason
    category: str = "auto_corrected"
    message: str
    edge_id: str | None = None
    source: str | None = None
    target: str | None = None
    original_value: str | None = None
    corrected_value: str | None = None
    node_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ByReasonBreakdown(BaseModel):
    """Aggregated counts and top examples grouped by reason."""

    reason: str
    count: int
    top_examples: list[dict[str, Any]] = Field(default_factory=list)


class EdgeHealth(BaseModel):
    """Structured edge quality report for MCP responses and doctor output."""

    total_edges: int = 0
    total_dropped: int = 0
    total_auto_corrected: int = 0
    dropped_ratio: float = 0.0
    dropped_by_reason: list[ByReasonBreakdown] = Field(default_factory=list)
    auto_corrected_by_reason: list[ByReasonBreakdown] = Field(default_factory=list)
    impact_assessment: str = ""
    suggested_actions: list[str] = Field(default_factory=list)
