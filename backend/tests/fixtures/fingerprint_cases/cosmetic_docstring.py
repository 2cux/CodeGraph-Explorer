"""Base file for fingerprint testing.

Only the docstrings have been modified — no structural changes.
"""

import os
from pathlib import Path
from typing import Optional


def greet(name: str) -> str:
    """Return a friendly greeting message for the given name parameter."""
    return f"Hello, {name}!"


def add(a: int, b: int) -> int:
    """Add two integers together and return the computed sum."""
    return a + b


class Calculator:
    """A simple calculator class for basic arithmetic operations."""

    def __init__(self, initial: int = 0) -> None:
        """Initialize calculator with an optional starting value."""
        self.value = initial

    def add(self, x: int) -> int:
        """Add the given value x to the calculator's current value."""
        self.value += x
        return self.value

    def get_value(self) -> int:
        """Return the calculator's current accumulated value."""
        return self.value


def main() -> None:
    """Application entry point — creates calculator and prints results."""
    calc = Calculator(10)
    result = calc.add(5)
    name = greet("World")
    print(f"{name} Result: {result}")
    print(add(1, 2))


if __name__ == "__main__":
    main()
