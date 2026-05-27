"""Authentication module."""

from app.store.token_store import save_token, revoke_token


def login(username: str, password: str) -> str:
    token = f"token_{username}"
    save_token(token)
    return token


def logout(token: str) -> None:
    revoke_token(token)
