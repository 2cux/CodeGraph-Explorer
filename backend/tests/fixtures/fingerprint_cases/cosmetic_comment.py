"""Base file for fingerprint testing — original version with extra comments."""

# This is a new comment added to the top of the file
# It does not change any structure

import os
from pathlib import Path
from typing import Optional


def greet(name: str) -> str:
    """Return a greeting for the given name."""
    # Added inline comment — still cosmetic
    return f"Hello, {name}!"


def add(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


class Calculator:
    """A simple calculator class."""

    def __init__(self, initial: int = 0) -> None:
        # Comment about initialization
        self.value = initial

    def add(self, x: int) -> int:
        """Add x to the current value."""
        self.value += x
        return self.value

    def get_value(self) -> int:
        """Return the current value."""
        return self.value


def main() -> None:
    """Main entry point."""
    calc = Calculator(10)
    result = calc.add(5)
    name = greet("World")
    # Print results — cosmetic comment
    print(f"{name} Result: {result}")
    print(add(1, 2))


if __name__ == "__main__":
    main()
