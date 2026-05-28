"""Token storage module with MFA pending-session support.

NOTE: Python 3.6 compatible -- uses ``typing.Dict`` (not ``dict[...]``).
"""

import secrets
from typing import Dict, Optional

_tokens: Dict[str, bool] = {}
_pending_mfa: Dict[str, str] = {}  # session_id -> username


def save_token(token: str) -> None:
    _tokens[token] = True


def revoke_token(token: str) -> None:
    _tokens.pop(token, None)


def is_valid(token: str) -> bool:
    return _tokens.get(token, False)


# ---- MFA pending session helpers ----


def create_pending_session(username: str) -> str:
    """Create a pending MFA session and return its ID."""
    session_id = "mfa_{}".format(secrets.token_hex(16))
    _pending_mfa[session_id] = username
    return session_id


def get_pending_username(session_id: str) -> Optional[str]:
    """Return the username associated with a pending session, or None."""
    return _pending_mfa.get(session_id)


def remove_pending_session(session_id: str) -> None:
    """Delete a pending session (after completion or expiry)."""
    _pending_mfa.pop(session_id, None)
