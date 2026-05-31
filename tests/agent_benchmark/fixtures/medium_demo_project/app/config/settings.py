"""Application configuration."""

from dataclasses import dataclass


@dataclass
class Settings:
    """Global application settings loaded from environment."""

    app_version: str = "1.0.0"
    debug: bool = False
    token_expiry_hours: int = 24
    max_sessions_per_user: int = 10
    mfa_required_for_admin: bool = True
    password_min_length: int = 8
    rate_limit_per_minute: int = 60

    def is_production(self) -> bool:
        """Check if running in production mode."""
        return not self.debug
