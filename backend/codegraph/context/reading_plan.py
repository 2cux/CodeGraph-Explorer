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
    model_ids: list[str] | None = None,
    store_ids: list[str] | None = None,
    has_suggested_tests: bool = False,
    has_route_handler: bool = False,
    max_steps: int = 10,
    low_confidence_ids: set[str] | None = None,
) -> list[ReadingStep]:
    """Build an ordered reading plan from entry points outward.

    The reading order follows the principle:
      1. Entry points first (the main symbols to understand)
      2. Upstream callers (high confidence first)
      3. Downstream callees (high confidence first)
      4. Data models / schemas (what data shapes are involved)
      5. Configuration / settings (what flags or env vars affect behavior)
      6. Store / persistence (how data is persisted)
      7. Related tests (verify behavior), or suggest writing tests
      8. Low-confidence items (optional — verify before relying)
      9. Config / model files (supporting definitions — fallback)

    Low-confidence items (below 0.60) are deferred to the end of the plan
    with a warning prefix so the agent knows to verify them.
    """
    steps: list[ReadingStep] = []
    step_num = 0
    seen: set[str] = set()
    low_ids = low_confidence_ids or set()
    # Collect low-confidence items separately for later addition
    low_conf_steps: list[tuple[str, str, str]] = []

    def _add(target: str, reason: str, action: str = "read_symbol") -> None:
        nonlocal step_num
        if target in seen or step_num >= max_steps:
            return
        seen.add(target)
        step_num += 1

        if target in low_ids:
            # Defer low-confidence items — collect for later
            low_conf_steps.append((target, reason, action))
            step_num -= 1  # don't count against budget yet
            seen.discard(target)
            return

        steps.append(ReadingStep(
            step=step_num,
            action=action,
            target=target,
            reason=reason,
        ))

    # ── Step 1-N: Entry points ────────────────────────────────────────────
    is_first_ep = True
    for sym_id in entry_point_ids:
        if has_route_handler and is_first_ep:
            _add(sym_id, "Start from HTTP route handler — this is the external request entry point and defines the API contract.")
        else:
            _add(sym_id, "Start from entry point — this is the most relevant symbol for the task.")
        is_first_ep = False

    # ── Next: Upstream callers (who invokes this code) ─────────────────────
    for sym_id in caller_ids:
        _add(sym_id, "Review upstream caller — understand who invokes this code and why.")

    # ── Next: Downstream callees (dependencies) ────────────────────────────
    for sym_id in callee_ids:
        _add(sym_id, "Follow downstream call — understand what this entry point depends on.")

    # ── Next: Data models / schemas ──────────────────────────────────────
    if model_ids:
        for mid in model_ids:
            _add(mid, "Review data model or schema — understand the data shape and fields this task may modify.")

    # ── Next: Configuration / settings ───────────────────────────────────
    if config_ids:
        for cid in config_ids:
            _add(cid, "Review configuration — new features or changes often need new config fields or settings.")

    # ── Next: Store / persistence ────────────────────────────────────────
    if store_ids:
        for sid in store_ids:
            _add(sid, "Review persistence layer — data reads/writes may need corresponding store or repository updates.")

    # ── Next: Related tests ────────────────────────────────────────────────
    if test_ids:
        for test_id in test_ids:
            _add(test_id, "Related test directly covers the changed behavior — inspect to understand expected outcomes.",
                 action="read_test")
    elif has_suggested_tests:
        ep_list = ", ".join(entry_point_ids[:3]) if entry_point_ids else "task symbols"
        _add(
            ep_list,
            "No related tests found — write tests to cover the changed behavior before modifying code.",
            action="write_tests",
        )

    # ── Last: Low-confidence / optional items ──────────────────────────────
    for target, reason, action in low_conf_steps:
        if step_num >= max_steps:
            break
        seen.add(target)
        step_num += 1
        steps.append(ReadingStep(
            step=step_num,
            action=action,
            target=target,
            reason=f"[Low confidence] {reason}",
        ))

    return steps
