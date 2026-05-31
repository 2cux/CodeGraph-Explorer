"""Authentication middleware for request validation."""

from app.api.auth import get_current_user


class AuthMiddleware:
    """Validates authentication tokens on incoming requests."""

    def __init__(self, require_auth: bool = True) -> None:
        self.require_auth = require_auth

    def process(self, token: str | None) -> dict:
        """Validate the request token and return user context."""
        if token is None:
            if self.require_auth:
                return {"authenticated": False, "error": "missing token"}
            return {"authenticated": False, "role": "anonymous"}
        result = get_current_user(token)
        if not result["authenticated"] and self.require_auth:
            return {"authenticated": False, "error": "invalid token"}
        return result

    def require_role(self, user_ctx: dict, allowed_roles: list[str]) -> bool:
        """Check if the authenticated user has a permitted role."""
        if not user_ctx.get("authenticated"):
            return False
        return user_ctx.get("role") in allowed_roles
