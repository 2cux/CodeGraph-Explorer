"""CLI entry point for codegraph commands."""

import typer

app = typer.Typer(
    name="codegraph",
    help="CodeGraph Explorer - AI Agent-first code context tool",
)


@app.command()
def index():
    """Scan the codebase, parse AST, and build code graph index."""
    ...


@app.command()
def context():
    """Generate a Context Pack for a natural language task."""
    ...


@app.command()
def search():
    """Search for code symbols across the indexed codebase."""
    ...


@app.command()
def explain():
    """Explain a symbol's call relationships."""
    ...


@app.command()
def impact():
    """Analyze the impact surface of modifying a symbol."""
    ...


@app.command()
def dashboard():
    """Start the local Dashboard (FastAPI backend + React frontend)."""
    ...
