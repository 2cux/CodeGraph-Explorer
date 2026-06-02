"""Module A handlers — also contains a close() function for name-conflict testing."""


def close() -> None:
    """Close a handler in module A (different from connections.close)."""
    pass


def handle_request() -> str:
    """Handle an incoming request."""
    close()
    return "ok"
