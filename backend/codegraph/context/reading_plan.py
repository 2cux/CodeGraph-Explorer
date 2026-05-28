"""Reading plan generation — ordered steps for understanding code.

PRD §13.8 — Reading Plan schema.
PRD §14.2 step 8 — Reading plan generation in the pipeline.
"""

from codegraph.context.models import ReadingStep


def is_config_file(file_path: str) -> bool:
    """Heuristic: config / settings / constants / schema modules."""
    lower = file_path.lower()
    keywords = ("config", "settings", "constants", "schema", "models", "types",
                "defaults", "presets", "env", "vars")
    stem = lower.split("/")[-1].replace(".py", "")
    return any(kw in stem for kw in keywords)


def build_reading_plan(
    entry_point_ids: list[str],
    callee_ids: list[str],
    caller_ids: list[str],
    test_ids: list[str],
    config_ids: list[str] | None = None,
    has_suggested_tests: bool = False,
    max_steps: int = 10,
) -> list[ReadingStep]:
    """Build an ordered reading plan from entry points outward.

    The reading order follows the principle:
      1. Entry points first (the main symbols to understand)
      2. Upstream callers (who invokes this code — understand the entry context)
      3. Downstream callees (what this code depends on)
      4. Related tests (verify behavior), or suggest writing tests
      5. Config / model files (supporting definitions)

    Each step includes a ``reason`` explaining why this step matters.
    """
    steps: list[ReadingStep] = []
    step_num = 0
    seen: set[str] = set()

    def _add(target: str, reason: str, action: str = "read_symbol") -> None:
        nonlocal step_num
        if target in seen or step_num >= max_steps:
            return
        seen.add(target)
        step_num += 1
        steps.append(ReadingStep(
            step=step_num,
            action=action,
            target=target,
            reason=reason,
        ))

    # ── Step 1-N: Entry points ────────────────────────────────────────────
    for sym_id in entry_point_ids:
        _add(sym_id, "Start from entry point — this is the most relevant symbol for the task.")

    # ── Next: Upstream callers (who invokes this code) ─────────────────────
    for sym_id in caller_ids:
        _add(sym_id, "Review upstream caller — understand who invokes this code and why.")

    # ── Next: Downstream callees (dependencies) ────────────────────────────
    for sym_id in callee_ids:
        _add(sym_id, "Follow downstream call — understand what this entry point depends on.")

    # ── Next: Related tests ────────────────────────────────────────────────
    if test_ids:
        for test_id in test_ids:
            _add(test_id, "Check related tests — verify behavior and catch regressions.")
    elif has_suggested_tests:
        ep_list = ", ".join(entry_point_ids[:3]) if entry_point_ids else "task symbols"
        _add(
            ep_list,
            "Add tests covering the entry points — no existing tests detected.",
            action="write_tests",
        )

    # ── Next: Config / model / supporting files ────────────────────────────
    if config_ids:
        for cid in config_ids:
            _add(cid, "Review supporting definition — config, model, or schema file.")

    return steps
