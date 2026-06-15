"""Fixture: same functions and structure but different imports.

This file has identical structural_hash and symbols_hash to
architecture_base.py but different imports_hash, which should
trigger ChangeType.ARCHITECTURE.
"""

import os
import json
from pathlib import Path
from datetime import datetime


def calculate_total(items):
    """Sum a list of numbers."""
    return sum(items)


def format_result(value, prefix=""):
    """Format a value with an optional prefix."""
    return f"{prefix}{value}"


class DataProcessor:
    """Process data with configurable settings."""

    def __init__(self, config=None):
        self.config = config or {}

    def process(self, data):
        """Process input data."""
        result = calculate_total(data)
        return format_result(result, prefix="total=")
