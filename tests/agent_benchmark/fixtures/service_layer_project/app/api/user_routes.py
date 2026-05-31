"""Route handlers for the user API."""

from app.services.user_service import UserService
from app.models.user import UserCreateRequest, UserResponse


_user_service = UserService()


def create_user(request: UserCreateRequest) -> UserResponse:
    """Create a new user account."""
    return _user_service.create_user(request)


def get_user(user_id: int) -> UserResponse:
    """Retrieve user by ID."""
    return _user_service.get_user(user_id)


def update_user(user_id: int, request: UserCreateRequest) -> UserResponse:
    """Update an existing user's profile."""
    return _user_service.update_user(user_id, request)


def delete_user(user_id: int) -> bool:
    """Delete a user account."""
    return _user_service.delete_user(user_id)
