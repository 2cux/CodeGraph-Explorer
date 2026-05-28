"""User data model.

NOTE: Uses a plain class (not dataclass) for Python 3.6 compatibility.
"""

from typing import Optional


class User:
    """A user in the demo system."""

    def __init__(self, name: str, role: str, mfa_secret: Optional[str] = None) -> None:
        self.name = name
        self.role = role
        # None means MFA is not enabled for this user.
        self.mfa_secret = mfa_secret

    def __repr__(self) -> str:
        return f"User(name={self.name!r}, role={self.role!r}, mfa_secret=...)"
