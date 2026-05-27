"""Reading plan generation — ordered steps for understanding code."""

from codegraph.context.models import ReadingStep


def build_reading_plan(
    entry_point_ids: list[str],
    related_ids: list[str],
    max_steps: int = 10,
) -> list[ReadingStep]:
    """Build an ordered reading plan from entry points outward.

    Each step is a ReadingStep with step number, action (read_symbol/read_file),
    target (symbol_id or file_path), and a reason string.
    """
    ...
