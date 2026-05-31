"""User data store — in-memory user registry."""

from typing import Optional
from app.models.user import User, Role


class UserStore:
    """In-memory user data store with search capability."""

    def __init__(self) -> None:
        self._users: dict[int, User] = {}
        self._by_username: dict[str, User] = {}

    def insert(self, user: User) -> None:
        """Add a user to the store."""
        self._users[user.id] = user
        self._by_username[user.username] = user

    def find_by_id(self, user_id: int) -> Optional[User]:
        """Look up user by ID."""
        return self._users.get(user_id)

    def find_by_username(self, username: str) -> Optional[User]:
        """Look up user by username."""
        return self._by_username.get(username)

    def update(self, user: User) -> None:
        """Update an existing user record."""
        self._users[user.id] = user
        self._by_username[user.username] = user

    def delete(self, user_id: int) -> bool:
        """Remove a user from the store."""
        user = self._users.pop(user_id, None)
        if user:
            self._by_username.pop(user.username, None)
            return True
        return False

    def search(self, query: str) -> list[User]:
        """Find users by username or email prefix."""
        q = query.lower()
        results: list[User] = []
        for user in self._users.values():
            if q in user.username.lower() or q in user.email.lower():
                results.append(user)
        return results

    def count(self) -> int:
        """Total number of users in the store."""
        return len(self._users)
