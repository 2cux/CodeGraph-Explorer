"""User model and role enum."""

from __future__ import annotations
from enum import Enum
from typing import Optional
import hashlib


class Role(str, Enum):
    """User permission roles."""
    admin = "admin"
    member = "member"
    viewer = "viewer"


class User:
    """Represents a registered user with credentials and role."""

    _next_id: int = 1

    def __init__(
        self,
        username: str,
        email: str = "",
        role: Role = Role.member,
        mfa_enabled: bool = False,
        mfa_secret: Optional[str] = None,
    ) -> None:
        self.id: int = User._next_id
        User._next_id += 1
        self.username: str = username
        self.email: str = email
        self.role: Role = role
        self.mfa_enabled: bool = mfa_enabled
        self.mfa_secret: Optional[str] = mfa_secret
        self._password_hash: str = ""

    def set_password(self, password: str) -> None:
        """Store a hashed version of the password."""
        self._password_hash = _hash_password(password)

    def check_password(self, password: str) -> bool:
        """Verify password against stored hash."""
        return self._password_hash == _hash_password(password)

    @classmethod
    def find_by_name(cls, username: str) -> Optional[User]:
        """Look up user by username from the global registry."""
        from app.store.user_store import UserStore
        return UserStore().find_by_username(username)

    @classmethod
    def reset_ids(cls) -> None:
        """Reset auto-increment counter (for tests)."""
        cls._next_id = 1


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()
