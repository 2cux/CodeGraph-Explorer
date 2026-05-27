"""Context Pack data models."""

from pydantic import BaseModel, Field


class RelatedSymbol(BaseModel):
    node_id: str
    name: str
    relevance: str  # "high" | "medium" | "low"
    reason: str


class CallGraphEntry(BaseModel):
    caller: str
    callee: str
    edge_type: str
    confidence: str


class ImpactEntry(BaseModel):
    symbol: str
    impact_type: str  # "direct" | "transitive" | "import_only"
    description: str


class ReadingStep(BaseModel):
    step: int
    file_path: str
    focus: str
    estimated_lines: int


class AgentInstructions(BaseModel):
    summary: str
    recommended_strategy: str
    warnings: list[str]


class ContextPack(BaseModel):
    task_description: str
    entry_points: list[RelatedSymbol]
    related_symbols: list[RelatedSymbol]
    call_graph: list[CallGraphEntry]
    impact: list[ImpactEntry]
    recommended_context: list[str]
    reading_plan: list[ReadingStep]
    agent_instructions: AgentInstructions
    total_tokens_estimate: int
