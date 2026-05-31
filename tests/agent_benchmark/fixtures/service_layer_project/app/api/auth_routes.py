"""Route handlers for authentication."""

from app.services.auth_service import AuthService


_auth_service = AuthService()


def login(username: str, password: str) -> dict:
    """Authenticate user and issue a token."""
    return _auth_service.login_user(username, password)


def logout(token: str) -> None:
    """Invalidate a session token."""
    _auth_service.logout_user(token)


def validate_token(token: str) -> dict:
    """Check if a token is still valid."""
    return _auth_service.validate_session(token)
