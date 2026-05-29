"""Reading plan generation — DEPRECATED in Evidence Pack.

This module is retained for backward compatibility with existing tests.
The Evidence Pack (Round 4) no longer generates reading plans, execution
orders, or agent instructions. New code should use the Evidence Pack
pipeline in pack_builder.py directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

# ── Local type stubs (these were moved out of models.py in Round 4) ────


class _ReadingAction(str, Enum):
    read_symbol = "read_symbol"
    read_test = "read_test"
    write_tests = "write_tests"
    review_config = "review_config"
    review_models = "review_models"
    review_store = "review_store"
    review_impact = "review_impact"
    review_domain_state = "review_domain_state"


class _ReadingStep(BaseModel):
    step: int
    action: _ReadingAction = _ReadingAction.read_symbol
    target: str
    reason: str = ""
    expected_outcome: str = ""
    linked_context_ids: list[str] = Field(default_factory=list)
    is_optional: bool = False
    step_kind: str = "main"


class _ReadingPlanDebug(BaseModel):
    plan_score: float = 0.0
    candidate_steps: list[dict] = Field(default_factory=list)
    dropped_steps: list[dict] = Field(default_factory=list)


# Re-export for backward compat
ReadingAction = _ReadingAction
ReadingStep = _ReadingStep
ReadingPlanDebug = _ReadingPlanDebug


# Import the shared models that still exist
from codegraph.context.models import (
    Impact,
    RelatedSymbol,
    RelatedTest,
)
from codegraph.context.selection import SelectedContext

# ── Backward-compat aliases ──────────────────────────────────────────

# RecommendedContext was renamed to SelectedContext in Round 4
RecommendedContext = SelectedContext


if TYPE_CHECKING:
    from codegraph.context.strategies import ContextStrategy


def is_config_file(file_path: str) -> bool:
    """Heuristic: config / settings / constants / schema modules."""
    lower = file_path.lower()
    keywords = ("config", "settings", "constants", "schema", "models", "types",
                "defaults", "presets", "env", "vars")
    stem = lower.split("/")[-1].replace(".py", "")
    return any(kw in stem for kw in keywords)


# ── Stub implementation: returns empty plan ──────────────────────────
# The Evidence Pack does not generate reading plans. This stub exists
# for backward compatibility with tests that still call this function.


def build_reading_plan(
    entry_point_ids=None,
    callee_ids=None,
    caller_ids=None,
    test_ids=None,
    config_ids=None,
    model_ids=None,
    store_ids=None,
    has_suggested_tests=False,
    has_route_handler=False,
    max_steps=10,
    low_confidence_ids=None,
    strategy=None,
    recommended_context=None,
    impact=None,
    related_symbols=None,
    existing_tests=None,
    suggested_tests=None,
    debug=False,
):
    """Stub: Evidence Pack no longer generates reading plans. Returns empty list."""
    return []


def build_reading_plan_debug(
    entry_point_ids=None,
    callee_ids=None,
    caller_ids=None,
    test_ids=None,
    config_ids=None,
    model_ids=None,
    store_ids=None,
    has_suggested_tests=False,
    has_route_handler=False,
    max_steps=10,
    low_confidence_ids=None,
    strategy=None,
    recommended_context=None,
    impact=None,
    related_symbols=None,
    existing_tests=None,
    suggested_tests=None,
):
    """Stub: Evidence Pack no longer generates reading plans. Returns empty."""
    return [], _ReadingPlanDebug()
