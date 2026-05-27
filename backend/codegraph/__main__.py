"""Allow ``python -m codegraph`` to invoke the CLI."""
from codegraph.cli.main import app

if __name__ == "__main__":
    app()
