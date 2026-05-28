"""Users module."""

from typing import List, Optional

from app.models.user import User


def get_users() -> List[User]:
    return [
        User(name="alice", role="admin", mfa_secret="JBSWY3DPEHPK3PXP"),
        User(name="bob", role="editor"),
    ]


def get_user_by_name(name: str) -> Optional[User]:
    users = get_users()
    for user in users:
        if user.name == name:
            return user
    return None
