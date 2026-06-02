"""Models module — defines User and TokenStore classes."""


class User:
    """A user model."""

    def __init__(self, name: str) -> None:
        self.name = name

    def save(self) -> None:
        """Save user to database."""
        pass


class TokenStore:
    """A token storage class."""

    def store_token(self, token: str) -> None:
        """Store a token."""
        pass

    def revoke_token(self, token: str) -> None:
        """Revoke a token."""
        pass
