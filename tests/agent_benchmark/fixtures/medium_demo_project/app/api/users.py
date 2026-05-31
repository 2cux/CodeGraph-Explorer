"""User management API endpoints."""

from app.models.user import User, Role
from app.services.user_service import UserService

_user_service = UserService()


def create_user(username: str, email: str, password: str, role: str = "member") -> dict:
    """Register a new user account."""
    return _user_service.register_user(username, email, password, Role(role))


def get_user_profile(user_id: int) -> dict:
    """Fetch a user's public profile."""
    return _user_service.get_profile(user_id)


def update_user_role(admin_user_id: int, target_user_id: int, new_role: str) -> dict:
    """Admin: change a user's role."""
    return _user_service.change_role(admin_user_id, target_user_id, Role(new_role))


def search_users(query: str) -> list[dict]:
    """Search users by username or email."""
    return _user_service.search(query)
