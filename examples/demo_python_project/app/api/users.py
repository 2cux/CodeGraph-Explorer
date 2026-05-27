"""Users module."""

from app.models.user import User


def get_users() -> list[User]:
    return [
        User(name="alice", role="admin"),
        User(name="bob", role="editor"),
    ]


def get_user_by_name(name: str) -> User | None:
    users = get_users()
    for user in users:
        if user.name == name:
            return user
    return None
