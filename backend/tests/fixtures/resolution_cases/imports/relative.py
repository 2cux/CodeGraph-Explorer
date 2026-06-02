"""Tests for relative import resolution."""

from .aliases import create_with_alias
from ..constructors.models import User


def use_relative_import() -> None:
    """Call a function imported via relative import."""
    create_with_alias("test")  # should resolve via relative import


def use_parent_relative_import() -> None:
    """Call User imported via parent-package relative import."""
    user = User("test")  # should resolve via relative import
    user.save()
