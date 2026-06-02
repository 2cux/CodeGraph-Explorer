"""Tests for self.method() and class method call resolution."""


class Worker:
    """A worker class with self.method() calls."""

    def __init__(self) -> None:
        self.ready = False

    def start(self) -> None:
        """Start the worker."""
        self.init_resources()  # self.method() — should resolve to same-class method
        self.ready = True

    def init_resources(self) -> None:
        """Initialize resources."""
        pass

    def stop(self) -> None:
        """Stop the worker."""
        self.cleanup()  # self.method() — should resolve to same-class method

    def cleanup(self) -> None:
        """Clean up resources."""
        pass
