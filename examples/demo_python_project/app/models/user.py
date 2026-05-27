"""User data model."""

from dataclasses import dataclass


@dataclass
class User:
    name: str
    role: str
