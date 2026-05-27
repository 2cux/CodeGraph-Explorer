"""Reading plan generation — ordered steps for understanding code."""

from codegraph.context.models import ReadingStep


def build_reading_plan(
    entry_point_ids: list[str],
    related_ids: list[str],
    max_steps: int = 10,
) -> list[ReadingStep]:
    """Generate an ordered reading plan from entry points outward."""
    ...
