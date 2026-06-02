"""Centralized confidence / resolution rules for all inference types.

Every inferred relationship in CodeGraph must carry a ``resolution`` and
``confidence`` value drawn from this module.  The mapping is the single
source of truth — callers must not hard-code confidence numbers.

Confidence levels (PRD §12.8):
  high:    >= 0.80   — strong signal, safe to follow
  medium:  0.60–0.79 — plausible, verify before relying
  low:     0.40–0.59 — weak hint, use as fallback only
  unknown: < 0.40    — opaque / unresolved, may be noise
"""

from __future__ import annotations

from codegraph.graph.models import Resolution

# ═══════════════════════════════════════════════════════════════════════════
# Master confidence table
# ═══════════════════════════════════════════════════════════════════════════

RESOLUTION_CONFIDENCE: dict[Resolution, float] = {
    # ── Structural / exact ──────────────────────────────────────────
    Resolution.exact_ast_match: 1.0,

    # ── Call resolution (ordered by signal strength) ────────────────
    Resolution.same_file_exact: 0.95,
    Resolution.imported_function_exact: 0.90,
    Resolution.self_method_resolved: 0.90,
    Resolution.imported_function_alias: 0.88,
    Resolution.imported_module_attribute: 0.88,
    Resolution.relative_import_resolved: 0.85,
    Resolution.parameter_type_hint_resolved: 0.82,
    Resolution.local_instance_resolved: 0.80,
    Resolution.module_instance_resolved: 0.78,
    Resolution.constructor_call_resolved: 0.75,
    Resolution.self_attribute_instance_resolved: 0.75,
    Resolution.same_module_fallback: 0.70,

    # ── Legacy / compat call resolutions ────────────────────────────
    Resolution.import_resolved: 0.90,
    Resolution.class_method_resolved: 0.80,
    Resolution.type_hint_resolved: 0.75,

    # ── TS/JS import resolution ─────────────────────────────────────
    Resolution.imported_symbol_exact: 0.90,
    Resolution.imported_alias_exact: 0.88,
    Resolution.default_import_exact: 0.90,
    Resolution.namespace_import_exact: 0.85,
    Resolution.relative_import_exact: 0.90,
    Resolution.barrel_export_resolved: 0.80,
    Resolution.this_method_exact: 0.90,
    Resolution.class_method_exact: 0.80,
    Resolution.require_exact: 0.88,
    Resolution.module_exports_exact: 0.85,

    # ── TS/JS possible / low-confidence ────────────────────────────
    Resolution.object_method_unknown: 0.35,
    Resolution.dynamic_property_access: 0.25,
    Resolution.callback_candidate: 0.30,

    # ── TS/JS unresolved / external ─────────────────────────────────
    Resolution.package_external: 0.50,
    Resolution.dynamic_import: 0.20,
    Resolution.require_unknown: 0.20,
    Resolution.computed_property: 0.15,
    Resolution.any_unknown: 0.15,

    # ── Route / entry-point detection ───────────────────────────────
    Resolution.fastapi_route_decorator: 0.95,
    Resolution.flask_route_decorator: 0.90,
    Resolution.django_view_heuristic: 0.65,
    Resolution.framework_route_resolved: 0.92,

    # ── Test discovery ──────────────────────────────────────────────
    Resolution.direct_test_call: 0.90,
    Resolution.test_import_match: 0.80,
    Resolution.test_name_heuristic: 0.65,
    Resolution.test_file_heuristic: 0.55,
    Resolution.suggested_test: 0.50,

    # ── Model / config / persistence detection ──────────────────────
    Resolution.pydantic_model_detected: 0.95,
    Resolution.dataclass_model_detected: 0.90,
    Resolution.sqlalchemy_model_detected: 0.85,
    Resolution.config_class_detected: 0.90,
    Resolution.config_constant_detected: 0.75,
    Resolution.repository_name_match: 0.70,
    Resolution.store_name_match: 0.70,
    Resolution.model_field_match: 0.80,
    Resolution.config_field_match: 0.75,
    Resolution.persistence_name_match: 0.70,

    # ── Ranking / context scoring ───────────────────────────────────
    Resolution.symbol_name_match: 0.95,
    Resolution.file_path_match: 0.75,
    Resolution.route_path_match: 0.85,
    Resolution.tag_match: 0.70,
    Resolution.field_name_match: 0.80,
    Resolution.call_graph_neighbor: 0.85,
    Resolution.impact_neighbor: 0.80,

    # ── Possible / low-confidence candidates ────────────────────────
    Resolution.name_match_candidate: 0.35,
    Resolution.filename_heuristic: 0.45,
    Resolution.docstring_reference: 0.40,

    # ── Unresolved / external / dynamic ─────────────────────────────
    Resolution.dynamic_getattr: 0.15,
    Resolution.reflection_call: 0.15,
    Resolution.unknown_external: 0.30,
    Resolution.decorator_unknown: 0.20,
    Resolution.import_not_found: 0.25,

    # ── Fallbacks ───────────────────────────────────────────────────
    Resolution.attribute_guess: 0.55,
    Resolution.external_symbol: 0.40,
    Resolution.unresolved: 0.20,
}

# ═══════════════════════════════════════════════════════════════════════════
# Public helpers
# ═══════════════════════════════════════════════════════════════════════════


def get_confidence(resolution: Resolution) -> float:
    """Return the canonical confidence value for a resolution strategy.

    Unknown resolutions default to 0.20 (``unresolved``).
    """
    return RESOLUTION_CONFIDENCE.get(resolution, 0.20)


def get_confidence_level(confidence: float) -> str:
    """Map a numeric confidence to a human-readable level.

    Returns one of ``"high"``, ``"medium"``, ``"low"``, ``"unknown"``.
    """
    if confidence >= 0.80:
        return "high"
    if confidence >= 0.60:
        return "medium"
    if confidence >= 0.40:
        return "low"
    return "unknown"


def is_low_confidence(confidence: float) -> bool:
    """True when confidence is below the medium threshold (0.60)."""
    return confidence < 0.60
