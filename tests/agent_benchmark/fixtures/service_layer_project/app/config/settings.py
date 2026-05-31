"""Application configuration."""


class Settings:
    """Global application settings."""

    def __init__(self) -> None:
        self.token_expiry_seconds: int = 3600
        self.max_sessions_per_user: int = 5
        self.password_min_length: int = 8
        self.debug: bool = False

    def get_token_lifetime(self) -> int:
        """Token validity period in seconds."""
        return self.token_expiry_seconds
