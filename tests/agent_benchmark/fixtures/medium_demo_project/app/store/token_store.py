"""Token storage with MFA pending-session support."""

import secrets
import time
from typing import Optional
from app.models.token import SessionToken


class TokenStore:
    """Manages authentication tokens and MFA pending sessions."""

    def __init__(self) -> None:
        self._tokens: dict[str, SessionToken] = {}
        self._pending_mfa: dict[str, str] = {}  # session_id -> username

    def save_token(self, username: str) -> str:
        """Create and persist an authentication token."""
        raw = "tok_" + secrets.token_hex(16)
        self._tokens[raw] = SessionToken(
            token=raw, username=username, created_at=time.time()
        )
        return raw

    def revoke_token(self, token: str) -> None:
        """Remove a token from the active session store."""
        self._tokens.pop(token, None)

    def validate_token(self, token: str) -> Optional[str]:
        """Return username if token is valid, None otherwise."""
        session = self._tokens.get(token)
        if session is None:
            return None
        if session.is_expired():
            self._tokens.pop(token, None)
            return None
        return session.username

    def count_sessions(self) -> int:
        """Return the number of active sessions."""
        return len(self._tokens)

    def list_sessions(self) -> list[dict]:
        """List all active sessions with metadata."""
        return [
            {"token": s.token, "username": s.username, "created_at": s.created_at}
            for s in self._tokens.values()
        ]

    def revoke_all_for_user(self, username: str) -> int:
        """Revoke all tokens for a specific user. Returns count revoked."""
        to_remove = [
            t for t, s in self._tokens.items() if s.username == username
        ]
        for t in to_remove:
            del self._tokens[t]
        return len(to_remove)

    # MFA pending sessions

    def create_pending_session(self, username: str) -> str:
        """Create an MFA pending session. Returns session ID."""
        session_id = "mfa_" + secrets.token_hex(16)
        self._pending_mfa[session_id] = username
        return session_id

    def get_pending_username(self, session_id: str) -> Optional[str]:
        """Return username for pending MFA session, or None."""
        return self._pending_mfa.get(session_id)

    def remove_pending_session(self, session_id: str) -> None:
        """Delete a pending MFA session."""
        self._pending_mfa.pop(session_id, None)
