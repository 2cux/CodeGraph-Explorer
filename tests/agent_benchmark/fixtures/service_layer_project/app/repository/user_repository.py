"""User data access layer."""

from typing import Optional
from app.models.user import UserCreateRequest


class UserRepository:
    """Manages user records in the database."""

    def __init__(self) -> None:
        self._users: dict[int, dict] = {}
        self._next_id: int = 1

    def find_by_id(self, user_id: int) -> Optional[dict]:
        """Look up a user by primary key."""
        return self._users.get(user_id)

    def find_by_username(self, username: str) -> Optional[dict]:
        """Look up a user by their username."""
        for user in self._users.values():
            if user.get("username") == username:
                return user
        return None

    def insert_user(self, request: UserCreateRequest) -> int:
        """Create a new user record. Returns the new ID."""
        user_id = self._next_id
        self._next_id += 1
        self._users[user_id] = {
            "id": user_id,
            "username": request.username,
            "email": request.email,
            "password_hash": _hash(request.password),
        }
        return user_id

    def update_user(self, user_id: int, request: UserCreateRequest) -> None:
        """Update an existing user's fields."""
        if user_id not in self._users:
            raise ValueError(f"User {user_id} not found")
        self._users[user_id].update({
            "username": request.username,
            "email": request.email,
        })

    def delete_user(self, user_id: int) -> bool:
        """Remove a user record. Returns True if deleted."""
        if user_id in self._users:
            del self._users[user_id]
            return True
        return False


def _hash(password: str) -> str:
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()
