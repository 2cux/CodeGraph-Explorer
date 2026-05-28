"""Authentication module with MFA support.

Login flow:
1. ``login()`` checks for the user and, if MFA is enabled, returns a
   pending session ID instead of a token.
2. The caller must then call ``verify_mfa()`` with the session ID and a
   valid TOTP code to obtain the final authentication token.
3. Users without MFA configured login immediately.
"""

from typing import Optional

from app.api.mfa import verify_totp
from app.api.users import get_user_by_name
from app.store.token_store import (
    create_pending_session,
    get_pending_username,
    remove_pending_session,
    revoke_token,
    save_token,
)


class LoginResult:
    """Result of a login or MFA-verification attempt."""

    def __init__(
        self,
        success: bool,
        token: Optional[str] = None,
        session_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        self.success = success
        self.token = token
        self.session_id = session_id
        self.error = error

    def __repr__(self) -> str:
        return (
            f"LoginResult(success={self.success}, token={self.token!r}, "
            f"session_id={self.session_id!r}, error={self.error!r})"
        )


def login(username: str, password: str) -> LoginResult:
    """Initiate a login.

    If the user has MFA enabled, a pending session is created and its
    ID is returned.  The caller must complete login by calling
    ``verify_mfa()`` with a valid TOTP code.

    If MFA is not enabled, a token is issued immediately.
    """
    user = get_user_by_name(username)
    if user is None:
        return LoginResult(success=False, error="user not found")

    # Password check is intentionally minimal in this demo.
    if not password:
        return LoginResult(success=False, error="password required")

    if user.mfa_secret is not None:
        session_id = create_pending_session(username)
        return LoginResult(success=True, session_id=session_id)

    # No MFA -- issue token directly.
    token = "token_{}".format(username)
    save_token(token)
    return LoginResult(success=True, token=token)


def verify_mfa(session_id: str, code: str) -> LoginResult:
    """Complete an MFA-protected login by verifying a TOTP code.

    Args:
        session_id: The pending session ID from ``login()``.
        code: 6-digit TOTP code.

    Returns:
        ``LoginResult`` with a ``token`` on success.
    """
    username = get_pending_username(session_id)
    if username is None:
        return LoginResult(success=False, error="invalid or expired session")

    user = get_user_by_name(username)
    if user is None or user.mfa_secret is None:
        remove_pending_session(session_id)
        return LoginResult(success=False, error="MFA not configured for this user")

    if not verify_totp(user.mfa_secret, code):
        return LoginResult(success=False, error="invalid MFA code")

    remove_pending_session(session_id)
    token = "token_{}".format(username)
    save_token(token)
    return LoginResult(success=True, token=token)


def logout(token: str) -> None:
    """Revoke an authentication token."""
    revoke_token(token)
