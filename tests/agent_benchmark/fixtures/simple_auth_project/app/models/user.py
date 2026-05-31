"""User model with password hashing."""

import hashlib
from typing import Optional


class User:
    """Represents a registered user."""

    def __init__(self, username: str, password_hash: str) -> None:
        self.username = username
        self.password_hash = password_hash

    def check_password(self, password: str) -> bool:
        """Verify password against stored hash."""
        return self.password_hash == _hash_password(password)

    @classmethod
    def find_by_name(cls, username: str) -> Optional["User"]:
        """Look up a user by username. Returns None if not found."""
        return _user_db.get(username)


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# Simulated user database
_user_db: dict[str, User] = {
    "admin": User("admin", _hash_password("admin123")),
    "alice": User("alice", _hash_password("alice123")),
}
