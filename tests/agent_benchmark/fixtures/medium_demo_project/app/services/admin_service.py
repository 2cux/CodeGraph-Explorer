"""Admin service — system monitoring and management."""

from app.store.token_store import TokenStore
from app.store.user_store import UserStore


class AdminService:
    """Administrative operations for the system."""

    def __init__(self) -> None:
        self._token_store = TokenStore()
        self._user_store = UserStore()

    def collect_stats(self) -> dict:
        """Aggregate system-wide metrics."""
        return {
            "total_users": self._user_store.count(),
            "active_sessions": self._token_store.count_sessions(),
            "version": "1.0.0",
        }

    def get_active_sessions(self) -> list[dict]:
        """Get all currently active user sessions."""
        return self._token_store.list_sessions()

    def force_logout(self, username: str) -> int:
        """Revoke all tokens belonging to a specific user."""
        return self._token_store.revoke_all_for_user(username)
