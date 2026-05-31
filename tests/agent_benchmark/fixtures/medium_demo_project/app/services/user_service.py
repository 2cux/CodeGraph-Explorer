"""User service — business logic for user management."""

from app.models.user import User, Role
from app.store.user_store import UserStore


class UserService:
    """Handles user registration, profile, roles, and search."""

    def __init__(self) -> None:
        self._user_store = UserStore()

    def register_user(self, username: str, email: str, password: str, role: Role) -> dict:
        """Create a new user account."""
        if self._user_store.find_by_username(username) is not None:
            return {"success": False, "error": "username taken"}
        user = User(username=username, email=email, role=role)
        user.set_password(password)
        self._user_store.insert(user)
        return {"success": True, "user_id": user.id}

    def get_profile(self, user_id: int) -> dict:
        """Return a user's public profile data."""
        user = self._user_store.find_by_id(user_id)
        if user is None:
            return {"success": False, "error": "user not found"}
        return {
            "success": True,
            "username": user.username,
            "email": user.email,
            "role": user.role.value,
        }

    def change_role(self, admin_id: int, target_id: int, new_role: Role) -> dict:
        """Change a user's role (requires admin)."""
        admin = self._user_store.find_by_id(admin_id)
        if admin is None or admin.role != Role.admin:
            return {"success": False, "error": "permission denied"}
        target = self._user_store.find_by_id(target_id)
        if target is None:
            return {"success": False, "error": "target user not found"}
        target.role = new_role
        self._user_store.update(target)
        return {"success": True}

    def search(self, query: str) -> list[dict]:
        """Search users by name or email prefix."""
        results = self._user_store.search(query)
        return [
            {"id": u.id, "username": u.username, "email": u.email, "role": u.role.value}
            for u in results
        ]
