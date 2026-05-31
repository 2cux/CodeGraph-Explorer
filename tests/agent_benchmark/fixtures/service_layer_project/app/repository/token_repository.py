"""Token persistence layer."""

import secrets
from typing import Optional


class TokenRepository:
    """Manages session tokens in storage."""

    def __init__(self) -> None:
        self._tokens: dict[str, int] = {}  # token -> user_id

    def create_token(self, user_id: int) -> str:
        """Generate and persist a new token."""
        token = "sess_" + secrets.token_hex(16)
        self._tokens[token] = user_id
        return token

    def lookup_token(self, token: str) -> Optional[int]:
        """Return user_id for a valid token, or None."""
        return self._tokens.get(token)

    def delete_token(self, token: str) -> None:
        """Remove a token from storage."""
        self._tokens.pop(token, None)

    def count_active(self) -> int:
        """Return the number of active sessions."""
        return len(self._tokens)
