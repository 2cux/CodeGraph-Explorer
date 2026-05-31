"""Business logic for authentication."""

import secrets
from app.repository.token_repository import TokenRepository
from app.repository.user_repository import UserRepository
from app.config.settings import Settings


class AuthService:
    """Handles login, logout, and token validation."""

    def __init__(self) -> None:
        self._token_repo = TokenRepository()
        self._user_repo = UserRepository()
        self._settings = Settings()

    def login_user(self, username: str, password: str) -> dict:
        """Verify credentials and create a session token."""
        user = self._user_repo.find_by_username(username)
        if user is None:
            return {"success": False, "error": "user not found"}
        if not self._verify_password(user, password):
            return {"success": False, "error": "invalid password"}
        token = self._token_repo.create_token(user["id"])
        return {"success": True, "token": token}

    def logout_user(self, token: str) -> None:
        """Remove the active session."""
        self._token_repo.delete_token(token)

    def validate_session(self, token: str) -> dict:
        """Check token validity and return user info."""
        user_id = self._token_repo.lookup_token(token)
        if user_id is None:
            return {"valid": False}
        user = self._user_repo.find_by_id(user_id)
        return {"valid": True, "username": user["username"] if user else None}

    def _verify_password(self, user: dict, password: str) -> bool:
        """Check password against stored hash."""
        return user.get("password_hash") == _hash(password)


def _hash(password: str) -> str:
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()
