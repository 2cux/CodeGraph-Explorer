"""认证模块 — test fixture for Chinese path and space compatibility."""


def login(username: str, password: str) -> str:
    """Authenticate a user and return a token."""
    return "token"


def logout(token: str) -> None:
    """Revoke a session token."""
    pass
