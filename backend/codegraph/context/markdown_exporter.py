"""Markdown export for Context Pack — human-readable output."""

from codegraph.context.models import ContextPack


def export_to_markdown(pack: ContextPack) -> str:
    """Render a ContextPack as a formatted Markdown string."""
    ...


def save_markdown(pack: ContextPack, output_path: str) -> None:
    """Write the Markdown export to a file."""
    ...
