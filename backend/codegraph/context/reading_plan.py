"""Reading plan generation — ordered steps for understanding code.

PRD §13.8 — Reading Plan schema.
PRD §14.2 step 8 — Reading plan generation in the pipeline.
"""

from codegraph.context.models import ReadingStep


def build_reading_plan(
    entry_point_ids: list[str],
    callee_ids: list[str],
    caller_ids: list[str],
    test_ids: list[str],
    max_steps: int = 10,
) -> list[ReadingStep]:
    """Build an ordered reading plan from entry points outward.

    The reading order follows the principle:
      1. Entry points first (the main symbols to understand)
      2. Direct callees (downstream dependencies)
      3. Direct callers (upstream dependents, if critical)
      4. Related tests

    Each step includes a ``reason`` explaining why this step matters.
    """
    steps: list[ReadingStep] = []
    step_num = 0
    seen: set[str] = set()

    def _add(target: str, reason: str) -> None:
        nonlocal step_num
        if target in seen or step_num >= max_steps:
            return
        seen.add(target)
        step_num += 1
        steps.append(ReadingStep(
            step=step_num,
            action="read_symbol",
            target=target,
            reason=reason,
        ))

    # ── Step 1-N: Entry points ────────────────────────────────────────────
    for sym_id in entry_point_ids:
        _add(sym_id, "Start from entry point — this is the most relevant symbol for the task.")

    # ── Next: Direct callees (downstream dependencies) ─────────────────────
    for sym_id in callee_ids:
        _add(sym_id, "Follow downstream call — understand what this entry point depends on.")

    # ── Next: Direct callers (upstream) ────────────────────────────────────
    for sym_id in caller_ids:
        _add(sym_id, "Review upstream caller — understand who invokes this code.")

    # ── Last: Related tests ────────────────────────────────────────────────
    for test_id in test_ids:
        _add(test_id, "Check related tests — verify behavior and catch regressions.")

    return steps
