"""Business logic for user management."""

from app.repository.user_repository import UserRepository
from app.models.user import UserCreateRequest, UserResponse


class UserService:
    """CRUD operations for users."""

    def __init__(self) -> None:
        self._user_repo = UserRepository()

    def create_user(self, request: UserCreateRequest) -> UserResponse:
        """Create a new user in the system."""
        user_id = self._user_repo.insert_user(request)
        user = self._user_repo.find_by_id(user_id)
        return UserResponse.from_dict(user)

    def get_user(self, user_id: int) -> UserResponse:
        """Fetch a user by ID."""
        user = self._user_repo.find_by_id(user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")
        return UserResponse.from_dict(user)

    def update_user(self, user_id: int, request: UserCreateRequest) -> UserResponse:
        """Update user profile fields."""
        self._user_repo.update_user(user_id, request)
        user = self._user_repo.find_by_id(user_id)
        return UserResponse.from_dict(user)

    def delete_user(self, user_id: int) -> bool:
        """Remove a user from the system."""
        return self._user_repo.delete_user(user_id)
