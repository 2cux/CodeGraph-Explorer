"""Token storage for session management."""

import secrets
from typing import Optional


class TokenStore:
    """In-memory token store for active sessions."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}  # token -> username

    def save_token(self, username: str) -> str:
        """Create and persist a new token for the given user."""
        token = "tok_" + secrets.token_hex(16)
        self._tokens[token] = username
        return token

    def revoke_token(self, token: str) -> None:
        """Remove a token from the active session store."""
        self._tokens.pop(token, None)

    def validate_token(self, token: str) -> Optional[str]:
        """Return username if token is valid, None otherwise."""
        return self._tokens.get(token)

    def count_sessions(self) -> int:
        """Return the number of active sessions."""
        return len(self._tokens)
