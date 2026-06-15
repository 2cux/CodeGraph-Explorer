"""Pydantic models for the enrichment pipeline.

Defines the schemas for:
- Prepare output (bounded input for agents)
- Agent output (what sub-agents produce)
- Validation results
- Enrichment status
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from typing import Any


# ── Prepare schemas ──────────────────────────────────────────────────


class PrepareProject(BaseModel):
    """Project metadata in prepare output."""

    name: str
    root: str
    language: str = "python"


class PrepareSymbol(BaseModel):
    """A symbol entry in prepare output (bounded input for agents)."""

    name: str
    type: str
    signature: str | None = None
    docstring: str | None = None
    snippet: str | None = None


class PrepareFile(BaseModel):
    """A file entry in prepare output."""

    path: str
    language: str
    symbols: list[PrepareSymbol] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)
    callers: list[dict[str, str]] = Field(default_factory=list)
    callees: list[dict[str, str]] = Field(default_factory=list)
    snippet: str | None = None


class PrepareConstraints(BaseModel):
    """Constraints that agents must respect."""

    schema_version: str = "codegraph_enrichment_v1"
    max_summary_chars: int = 500
    max_tags: int = 10
    relative_paths_only: bool = True
    evidence_required: bool = True
    confidence_values: list[str] = Field(
        default_factory=lambda: ["high", "medium", "low"]
    )


class PrepareOutput(BaseModel):
    """The full prepare output written to .codegraph/intermediate/enrich_input.json."""

    project: PrepareProject
    files: list[PrepareFile] = Field(default_factory=list)
    constraints: PrepareConstraints = Field(default_factory=PrepareConstraints)


# ── Agent output schemas ─────────────────────────────────────────────


class EnrichedEvidence(BaseModel):
    """Evidence reference pointing to a source location."""

    file: str
    line_start: int | None = None
    line_end: int | None = None


class EnrichedFile(BaseModel):
    """File-level enrichment produced by a file-enricher agent."""

    path: str
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    role: str = ""
    confidence: str = "medium"  # high | medium | low
    evidence: list[EnrichedEvidence] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def _check_confidence(cls, v: str) -> str:
        if v not in ("high", "medium", "low"):
            raise ValueError(f"confidence must be high/medium/low, got {v!r}")
        return v


class EnrichedSymbol(BaseModel):
    """Symbol-level enrichment produced by a symbol-enricher agent."""

    symbol: str
    file: str
    summary: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    edge_cases: list[str] = Field(default_factory=list)
    test_relevance: str = ""
    confidence: str = "medium"
    evidence: list[EnrichedEvidence] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def _check_confidence(cls, v: str) -> str:
        if v not in ("high", "medium", "low"):
            raise ValueError(f"confidence must be high/medium/low, got {v!r}")
        return v


class AgentOutput(BaseModel):
    """Schema for agent output JSON written to .codegraph/intermediate/."""

    schema_version: str = "codegraph_enrichment_v1"
    enriched_at: str = ""
    files: list[EnrichedFile] = Field(default_factory=list)
    symbols: list[EnrichedSymbol] = Field(default_factory=list)


# ── Validation schemas ───────────────────────────────────────────────


class ValidationError_(BaseModel):
    """A single validation error or warning."""

    path: str = ""  # e.g. "files[0].summary" or "symbols[2].file"
    message: str
    severity: str = "error"  # error | warning


class ValidationResult(BaseModel):
    """Result of the validate step."""

    valid: bool
    errors: list[ValidationError_] = Field(default_factory=list)
    warnings: list[ValidationError_] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)


# ── Status schemas ───────────────────────────────────────────────────


class EnrichmentStatus(BaseModel):
    """Returned by 'codegraph enrich status'."""

    total_nodes: int = 0
    enriched_nodes: int = 0
    pending_nodes: int = 0
    skipped_nodes: int = 0
    error_nodes: int = 0
    enriched_files: int = 0
    total_files: int = 0
    confidence_breakdown: dict[str, int] = Field(default_factory=dict)
    last_enriched_at: str = ""
