"""Admin API endpoints for system management."""

from app.services.admin_service import AdminService

_admin_service = AdminService()


def get_system_stats() -> dict:
    """Return system-wide statistics."""
    return _admin_service.collect_stats()


def list_active_sessions() -> list[dict]:
    """List all active user sessions."""
    return _admin_service.get_active_sessions()


def revoke_all_tokens(username: str) -> int:
    """Force-revoke all tokens for a user."""
    return _admin_service.force_logout(username)
