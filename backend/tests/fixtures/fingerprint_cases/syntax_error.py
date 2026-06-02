"""This file has a syntax error — used for testing fallback behavior."""

import os


def greet(name: str) -> str:
    return f"Hello, {name}!"


# Intentional syntax error below
def broken(
