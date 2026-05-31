"""Authentication module with login/logout flow."""

from app.models.user import User
from app.store.token_store import TokenStore

_token_store = TokenStore()


def login(username: str, password: str) -> dict:
    """Authenticate user and return a session token."""
    user = _find_user(username)
    if user is None:
        return {"success": False, "error": "user not found"}
    if not _check_password(user, password):
        return {"success": False, "error": "invalid password"}
    token = _token_store.save_token(username)
    return {"success": True, "token": token}


def logout(token: str) -> None:
    """Revoke an active session token."""
    _token_store.revoke_token(token)


def _find_user(username: str) -> User | None:
    """Internal: lookup user from database."""
    return User.find_by_name(username)


def _check_password(user: User, password: str) -> bool:
    """Internal: verify password hash."""
    return user.check_password(password)
