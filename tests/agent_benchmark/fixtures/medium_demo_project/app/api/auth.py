"""Authentication module with MFA support.

Login flow:
1. login() checks for user and, if MFA enabled, returns pending session
2. verify_mfa() completes login with TOTP code
3. Users without MFA login immediately.
"""

from app.models.user import User
from app.store.token_store import TokenStore
from app.services.mfa_service import MfaService

_token_store = TokenStore()
_mfa_service = MfaService()


def login(username: str, password: str) -> dict:
    """Initiate login. Returns token or pending session ID for MFA users."""
    user = User.find_by_name(username)
    if user is None:
        return {"success": False, "error": "user not found"}
    if not user.check_password(password):
        return {"success": False, "error": "invalid credentials"}
    if user.mfa_enabled:
        session_id = _token_store.create_pending_session(username)
        return {"success": True, "mfa_required": True, "session_id": session_id}
    token = _token_store.save_token(username)
    return {"success": True, "token": token}


def verify_mfa(session_id: str, code: str) -> dict:
    """Complete MFA login with TOTP verification."""
    username = _token_store.get_pending_username(session_id)
    if username is None:
        return {"success": False, "error": "invalid session"}
    user = User.find_by_name(username)
    if user is None or not user.mfa_enabled:
        _token_store.remove_pending_session(session_id)
        return {"success": False, "error": "mfa not configured"}
    if not _mfa_service.verify_code(user.mfa_secret, code):
        return {"success": False, "error": "invalid mfa code"}
    _token_store.remove_pending_session(session_id)
    token = _token_store.save_token(username)
    return {"success": True, "token": token}


def logout(token: str) -> None:
    """Revoke an active session token."""
    _token_store.revoke_token(token)


def get_current_user(token: str) -> dict:
    """Get the user associated with an active token."""
    username = _token_store.validate_token(token)
    if username is None:
        return {"authenticated": False}
    user = User.find_by_name(username)
    if user is None:
        return {"authenticated": False}
    return {"authenticated": True, "username": user.username, "role": user.role}
