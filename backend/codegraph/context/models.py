"""Context Pack data models — task-aware code context packages.

Matches PRD Section 13 (Context Pack Schema) specification.
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


# ── Task ─────────────────────────────────────────────────────────────


class TaskConstraints(BaseModel):
    max_tokens: int = 6000
    max_files: int = 8
    include_tests: bool = True


class Task(BaseModel):
    """Task description and parsed intent — PRD §13.2."""

    raw_request: str
    intent: TaskIntent = TaskIntent.understand_code
    keywords: list[str] = Field(default_factory=list)
    target_symbols: list[str] = Field(default_factory=list)
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)


# ── Entry Point ─────────────────────────────────────────────────────


class EntryPoint(BaseModel):
    """A matched entry point symbol — PRD §13.3."""

    symbol_id: str
    type: str
    name: str
    file_path: str
    location: dict | None = None
    signature: str | None = None
    reason: str = ""
    score: float = 0.0
    match_sources: list[str] = Field(default_factory=list)


# ── Related Symbol ──────────────────────────────────────────────────


class RelatedSymbol(BaseModel):
    """A symbol related to an entry point — PRD §13.4."""

    symbol_id: str
    relation: str = "related"
    distance: int = 1
    direction: str = "outgoing"
    reason: str = ""
    importance: Importance = Importance.medium
    confidence: float = 0.0


# ── Call Graph ──────────────────────────────────────────────────────


class CallGraphNode(BaseModel):
    """A node in the context pack's call graph — PRD §13.5."""

    id: str
    label: str
    type: str


class CallGraphEdge(BaseModel):
    """An edge in the context pack's call graph — PRD §13.5."""

    source: str
    target: str
    type: str = "calls"
    confidence: float = 0.0


class CallGraph(BaseModel):
    """Subgraph centered on the task's entry point — PRD §13.5."""

    center: str = ""
    depth: int = 1
    nodes: list[CallGraphNode] = Field(default_factory=list)
    edges: list[CallGraphEdge] = Field(default_factory=list)


# ── Impact ──────────────────────────────────────────────────────────


class AffectedSymbol(BaseModel):
    """A symbol affected by a change — PRD §13.6."""

    symbol_id: str
    reason: str = ""
    impact_type: ImpactType = ImpactType.unknown
    distance: int = 1
    confidence: float = 0.0


class AffectedFile(BaseModel):
    """A file affected by a change — PRD §13.6."""

    file_path: str
    reason: str = ""
    priority: str = "medium"


class Risk(BaseModel):
    """Risk assessment for a change — PRD §13.6."""

    level: RiskLevel = RiskLevel.low
    reasons: list[str] = Field(default_factory=list)


class Impact(BaseModel):
    """Full impact analysis result — PRD §13.6."""

    changed_symbol: str = ""
    affected_symbols: list[AffectedSymbol] = Field(default_factory=list)
    affected_files: list[AffectedFile] = Field(default_factory=list)
    risk: Risk = Field(default_factory=Risk)


# ── Recommended Context ──────────────────────────────────────────────


class RecommendedContext(BaseModel):
    """A single recommended context item — PRD §13.7."""

    context_id: str = ""
    type: ContextType = ContextType.code_snippet
    symbol_id: str = ""
    file_path: str = ""
    line_start: int = 0
    line_end: int = 0
    priority: str = "medium"
    reason: str = ""
    content: str = ""
    estimated_tokens: int = 0


# ── Reading Plan ─────────────────────────────────────────────────────


class RelatedTest(BaseModel):
    """A test file related to the task — existing or suggested.

    ``type`` is ``"existing"`` when a test was found in the index,
    or ``"suggested"`` when no matching tests exist and the system
    recommends creating one based on naming conventions.
    """

    type: str = "existing"
    test_file: str
    test_name: str = ""
    reason: str = ""
    confidence: float = 0.0


class ReadingStep(BaseModel):
    """A single step in the reading plan — PRD §13.8."""

    step: int
    action: str = "read_symbol"
    target: str
    reason: str = ""


# ── Agent Instructions ───────────────────────────────────────────────


class AgentInstructions(BaseModel):
    """Agent-facing instructions accompanying a Context Pack — PRD §13.9."""

    summary: str = ""
    recommended_strategy: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── Exports ──────────────────────────────────────────────────────────


class ExportsInfo(BaseModel):
    """Paths to exported files — PRD §13.1."""

    markdown_path: str = ""
    json_path: str = ""


# ── Top-level Context Pack ───────────────────────────────────────────


class ContextPack(BaseModel):
    """Top-level Context Pack container — PRD §13.1."""

    schema_version: str = "1.0.0"
    pack_id: str = ""
    task: Task = Field(default_factory=Task)
    repo: dict[str, Any] = Field(default_factory=dict)
    entry_points: list[EntryPoint] = Field(default_factory=list)
    related_symbols: list[RelatedSymbol] = Field(default_factory=list)
    call_graph: CallGraph = Field(default_factory=CallGraph)
    impact: Impact = Field(default_factory=Impact)
    recommended_context: list[RecommendedContext] = Field(default_factory=list)
    related_tests: list[RelatedTest] = Field(default_factory=list)
    reading_plan: list[ReadingStep] = Field(default_factory=list)
    agent_instructions: AgentInstructions = Field(default_factory=AgentInstructions)
    exports: ExportsInfo = Field(default_factory=ExportsInfo)
