"""Module B workers — contains wait() but does NOT import close()."""


def wait() -> None:
    """Wait in module B (different from connections.wait)."""
    pass


def run_worker() -> None:
    """Run a worker — calls close() without importing it.

    This close() call is a name-only match — it should NOT be a confirmed edge.
    """
    close()  # name-only — must be name_match_candidate, not confirmed
