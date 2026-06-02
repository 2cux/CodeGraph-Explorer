"""Base file for fingerprint testing — whitespace-only changes."""

import os
from pathlib import Path
from typing import Optional


def greet(name: str) -> str:
    """Return a greeting for the given name."""

    return f"Hello, {name}!"



def add(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


class Calculator:
    """A simple calculator class."""

    def __init__(self, initial: int = 0) -> None:

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

    print(f"{name} Result: {result}")

    print(add(1, 2))


if __name__ == "__main__":
    main()
