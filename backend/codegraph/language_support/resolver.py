"""Resolver interface — unified cross-file edge resolution.

Each language provides a :class:`Resolver` that takes a list of
:class:`ExtractorResult` objects and produces :class:`ResolvedEdges`
with provenance, resolution, confidence, and evidence on every
confirmed edge.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from pydantic import BaseModel, Field
from typing import Any

from codegraph.graph.models import EdgeType, Resolution, EdgeMetadata


# ── Provenance ──────────────────────────────────────────────────────────

class Provenance(str, Enum):
    """How an edge was discovered — the methodological source.

    Every confirmed edge must carry a provenance value so downstream
    consumers can assess methodological coverage and trust.
    """

    AST = "ast"
    """Directly observed in the abstract syntax tree (structural edges,
    same-file calls, etc.)."""

    IMPORT_RESOLVER = "import_resolver"
    """Resolved by tracing import statements to their target definitions."""

    TYPE_RESOLVER = "type_resolver"
    """Resolved by static type analysis (type hints, type inference)."""

    FRAMEWORK_RESOLVER = "framework_resolver"
    """Resolved by framework-specific conventions (route decorators,
    ORM models, DI containers, etc.)."""

    HEURISTIC = "heuristic"
    """Inferred via naming conventions, file layout, or other heuristic
    signals (test discovery, config detection, etc.)."""

    EXTERNAL_INDEX = "external_index"
    """Resolved against an external index or type-stub database."""


# ── Resolved edge ───────────────────────────────────────────────────────

class ResolvedEdge(BaseModel):
    """A single resolved edge ready for insertion into the code graph."""

    source: str
    target: str
    edge_type: EdgeType
    confidence: float
    resolution: Resolution
    provenance: Provenance
    evidence: dict[str, Any] = Field(default_factory=dict)
    source_location: dict[str, Any] | None = None
    metadata: EdgeMetadata | None = None


# ── Resolved edges container ────────────────────────────────────────────

class ResolvedEdges(BaseModel):
    """Result of the resolver phase — edges grouped by confidence tier.

    - **confirmed**: High-confidence edges ready for MCP consumption.
      Every entry carries ``provenance``, ``resolution``, ``confidence``,
      and ``evidence``.
    - **possible**: Lower-confidence edges provided as hints. Consumers
      should treat these as unverified.
    - **unresolved_candidates**: Name-only matches that could not be
      confirmed. These MUST NOT be treated as confirmed edges.
    """

    confirmed: list[ResolvedEdge] = Field(default_factory=list)
    possible: list[ResolvedEdge] = Field(default_factory=list)
    unresolved_candidates: list[ResolvedEdge] = Field(default_factory=list)


# ── Graph context helper ────────────────────────────────────────────────

class GraphContext(BaseModel):
    """Minimal graph state passed to resolvers for cross-file lookups.

    Provides qualified_name → node_id mappings and symbol counts
    without exposing the full graph store.
    """

    language_id: str
    qual_to_id: dict[str, str] = Field(default_factory=dict)
    name_to_ids: dict[str, list[str]] = Field(default_factory=dict)
    file_to_ids: dict[str, list[str]] = Field(default_factory=dict)
    node_count: int = 0


# ── Resolver interface ──────────────────────────────────────────────────

class Resolver(ABC):
    """Abstract base class for per-language cross-file edge resolvers.

    The resolver takes all per-file extraction results and the current
    graph context, then produces resolved edges with full provenance.
    """

    @abstractmethod
    def resolve(self,
                extractor_results: list[Any],  # list[ExtractorResult] — avoid circular import
                graph_context: GraphContext,
                import_index: dict[str, Any] | None = None,
                ) -> ResolvedEdges:
        """Resolve cross-file edges from extraction results.

        Args:
            extractor_results: Per-file :class:`ExtractorResult` objects
                               from the extract phase.
            graph_context: Current graph state for cross-file lookups
                           (qualified_name → node_id, name → node_ids, etc.).
            import_index: Optional language-specific import resolution index.

        Returns:
            :class:`ResolvedEdges` with confirmed, possible, and
            unresolved_candidates tiers.
        """
        ...
