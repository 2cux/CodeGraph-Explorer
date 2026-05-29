"""Context Pack data models — task-aware structured code evidence.

Evidence Pack: outputs only structured code facts (relationships, confidence,
evidence sources). No reading plans, execution orders, or agent instructions.
"""

from enum import Enum
from pydantic import BaseModel, Field
from typing import Any


# ── Enums ────────────────────────────────────────────────────────────


class TaskIntent(str, Enum):
    understand_code = "understand_code"
    modify_existing_behavior = "modify_existing_behavior"
    add_feature = "add_feature"
    fix_bug = "fix_bug"
    refactor = "refactor"
    write_tests = "write_tests"
    review_code = "review_code"
    analyze_impact = "analyze_impact"
    generate_docs = "generate_docs"


class OperationSignal(str, Enum):
    """What kind of operation the user wants to perform."""
    create = "create"
    modify = "modify"
    delete = "delete"
    understand = "understand"
    test = "test"
    document = "document"
    review = "review"
    analyze = "analyze"
    fix = "fix"
    refactor = "refactor"


class ConstraintType(str, Enum):
    """Constraints that modify how a task should be executed."""
    no_modify = "no_modify"
    preserve_behavior = "preserve_behavior"
    backward_compatible = "backward_compatible"
    with_tests = "with_tests"
    performance = "performance"
    security = "security"


class Importance(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class ImpactType(str, Enum):
    direct_definition = "direct_definition"
    upstream_caller = "upstream_caller"
    downstream_call = "downstream_call"
    shared_model = "shared_model"
    import_dependency = "import_dependency"
    test_coverage = "test_coverage"
    config_dependency = "config_dependency"
    unknown = "unknown"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ContextType(str, Enum):
    code_snippet = "code_snippet"
    file_summary = "file_summary"
    symbol_summary = "symbol_summary"
    call_chain = "call_chain"
    impact_summary = "impact_summary"
    test_reference = "test_reference"
    config_summary = "config_summary"
    model_summary = "model_summary"
    warning = "warning"


class RelationType(str, Enum):
    """Controlled vocabulary for RelatedSymbol.relation."""
    callee = "callee"
    caller = "caller"
    test = "test"
    model_dependency = "model_dependency"
    config_dependency = "config_dependency"
    persistence_dependency = "persistence_dependency"
    schema_dependency = "schema_dependency"
    import_dependency = "import_dependency"
    related = "related"


class Direction(str, Enum):
    outgoing = "outgoing"
    incoming = "incoming"


class PriorityLevel(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class TestSource(str, Enum):
    existing = "existing"
    suggested = "suggested"
    heuristic = "heuristic"


class ContentMode(str, Enum):
    full_source = "full_source"
    summary = "summary"
    reference = "reference"


class ConfidenceLevel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


class NoteType(str, Enum):
    """Allowed pack_note types — factual metadata only, no advice."""
    index_status = "index_status"
    confidence = "confidence"
    test_coverage_signal = "test_coverage_signal"
    token_budget = "token_budget"
    unresolved_symbols = "unresolved_symbols"
    competing_entry_points = "competing_entry_points"


# ── Location ─────────────────────────────────────────────────────────


class EntryPointLocation(BaseModel):
    """Source location for an entry point symbol."""
    line_start: int = 0
    line_end: int = 0
    column_start: int = 0
    column_end: int = 0


# ── Task ─────────────────────────────────────────────────────────────


class TaskConstraints(BaseModel):
    max_tokens: int = 6000
    max_files: int = 8
    include_tests: bool = True


class Task(BaseModel):
    """Task description and parsed intent."""

    raw_request: str
    intent: TaskIntent = TaskIntent.understand_code
    primary_intent: TaskIntent = TaskIntent.understand_code
    secondary_intents: list[TaskIntent] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    target_symbols: list[str] = Field(default_factory=list)
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)


# ── Entry Point ──────────────────────────────────────────────────────


class EntryPoint(BaseModel):
    """A candidate entry point symbol — matched by keyword, not a directive.

    ``reason`` must only describe the match basis (name match, keyword hit,
    call graph centrality). It must NOT contain directives like "start here",
    "read first", "you should", or "must".
    """

    symbol_id: str
    type: str
    name: str
    file_path: str
    location: EntryPointLocation | None = None
    signature: str | None = None
    reason: str = ""
    score: float = 0.0
    match_sources: list[str] = Field(default_factory=list)


# ── Related Symbol ───────────────────────────────────────────────────


class RelatedSymbol(BaseModel):
    """A symbol related to an entry point — relationship fact only."""

    symbol_id: str
    relation: RelationType = RelationType.related
    distance: int = 1
    direction: Direction = Direction.outgoing
    reason: str = ""
    importance: Importance = Importance.medium
    confidence: float = 0.0
    confidence_level: ConfidenceLevel = ConfidenceLevel.unknown


# ── Call Graph ───────────────────────────────────────────────────────


class CallGraphNode(BaseModel):
    """A node in the context pack's call graph."""

    id: str
    label: str
    type: str


class CallGraphEdge(BaseModel):
    """An edge in the context pack's call graph."""

    source: str
    target: str
    type: str = "calls"
    confidence: float = 0.0
    resolution: str = ""
    confidence_level: ConfidenceLevel = ConfidenceLevel.unknown


class CallGraph(BaseModel):
    """Subgraph centered on the task's entry point."""

    center: str = ""
    depth: int = 1
    nodes: list[CallGraphNode] = Field(default_factory=list)
    edges: list[CallGraphEdge] = Field(default_factory=list)


# ── Impact ───────────────────────────────────────────────────────────


class AffectedSymbol(BaseModel):
    """A symbol affected by a change."""

    symbol_id: str
    reason: str = ""
    impact_type: ImpactType = ImpactType.unknown
    distance: int = 1
    confidence: float = 0.0
    confidence_level: ConfidenceLevel = ConfidenceLevel.unknown


class AffectedFile(BaseModel):
    """A file affected by a change."""

    file_path: str
    reason: str = ""
    priority: PriorityLevel = PriorityLevel.medium


class Risk(BaseModel):
    """Risk assessment for a change."""

    level: RiskLevel = RiskLevel.low
    reasons: list[str] = Field(default_factory=list)


class Impact(BaseModel):
    """Full impact analysis result."""

    changed_symbol: str = ""
    affected_symbols: list[AffectedSymbol] = Field(default_factory=list)
    affected_files: list[AffectedFile] = Field(default_factory=list)
    risk: Risk = Field(default_factory=Risk)


# ── Selected Context ─────────────────────────────────────────────────


class SelectedContext(BaseModel):
    """A context item selected under token budget — evidence, not a directive.

    Each item carries its relation to the task, confidence, resolution,
    and evidence trace so the consumer can assess reliability independently.
    """

    context_id: str = ""
    type: ContextType = ContextType.code_snippet
    symbol_id: str = ""
    file_path: str = ""
    line_start: int = 0
    line_end: int = 0
    priority: PriorityLevel = PriorityLevel.medium
    relation: str = ""
    selection_reason: str = ""
    content: str = ""
    estimated_tokens: int = 0
    content_mode: ContentMode = ContentMode.full_source
    confidence: float = 0.0
    confidence_level: ConfidenceLevel = ConfidenceLevel.unknown
    resolution: str = ""
    evidence: str = ""
    context_score: float = 0.0


# ── Tests ────────────────────────────────────────────────────────────


class RelatedTest(BaseModel):
    """A test file related to the task.

    ``source`` is ``"existing"`` when a test was found in the index,
    ``"heuristic"`` when generated from naming conventions — heuristic
    tests carry lower confidence and are NOT directives to write them.
    """

    source: TestSource = TestSource.existing
    test_file: str
    test_name: str = ""
    reason: str = ""
    confidence: float = 0.0
    confidence_level: ConfidenceLevel = ConfidenceLevel.unknown


class TestsSection(BaseModel):
    """Combined test evidence — existing tests found + heuristic suggestions."""

    existing_tests: list[RelatedTest] = Field(default_factory=list)
    suggested_tests: list[RelatedTest] = Field(default_factory=list)


# ── Pack Notes ───────────────────────────────────────────────────────


class PackNote(BaseModel):
    """A factual note about the evidence pack's composition or limitations.

    Only allowed types: index_status, confidence, test_coverage_signal,
    token_budget, unresolved_symbols, competing_entry_points.

    Must NOT contain implementation advice, reading order, task plans,
    or any "should"/"must" directives.
    """

    type: NoteType
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


# ── Index Status ─────────────────────────────────────────────────────


class IndexStatus(BaseModel):
    """Metadata about the index used to produce this pack."""

    symbol_count: int = 0
    edge_count: int = 0
    index_format: str = "codegraph/v1"
    language: str = "python"


# ── Exports ──────────────────────────────────────────────────────────


class ExportsInfo(BaseModel):
    """Paths to exported files."""

    markdown_path: str = ""
    json_path: str = ""


# ── Top-level Evidence Pack ──────────────────────────────────────────


class ContextPack(BaseModel):
    """Top-level Evidence Pack — structured code facts, no action plan.

    This is the primary output of CodeGraph Explorer. It provides
    task-level code evidence: entry point candidates, related symbols,
    call graph, impact signals, selected context materials, tests,
    warnings, and pack metadata. It does NOT provide reading order,
    execution plans, or agent instructions.
    """

    schema_version: str = "1.0.0"
    pack_id: str = ""
    created_at: str = ""

    # Task description + detected intent
    task: Task = Field(default_factory=Task)

    # Repository metadata
    repo: dict[str, Any] = Field(default_factory=dict)

    # Index metadata
    index_status: IndexStatus = Field(default_factory=IndexStatus)

    # Candidate entry points (match-based, not directives)
    entry_points: list[EntryPoint] = Field(default_factory=list)

    # Related symbols (relationship facts only)
    related_symbols: list[RelatedSymbol] = Field(default_factory=list)

    # Call graph subgraph
    call_graph: CallGraph = Field(default_factory=CallGraph)

    # Impact signals
    impact: Impact = Field(default_factory=Impact)

    # Test evidence (existing + heuristic suggestions)
    tests: TestsSection = Field(default_factory=TestsSection)

    # Context materials selected under token budget
    selected_context: list[SelectedContext] = Field(default_factory=list)

    # Warnings about low-confidence or uncertain signals
    warnings: list[str] = Field(default_factory=list)

    # Factual metadata about the pack composition
    pack_notes: list[PackNote] = Field(default_factory=list)

    # Token budget tracking
    token_budget: dict[str, int] = Field(default_factory=dict)

    # Export paths
    exports: ExportsInfo = Field(default_factory=ExportsInfo)
