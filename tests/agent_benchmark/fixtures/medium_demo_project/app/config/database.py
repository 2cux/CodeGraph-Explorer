"""Database configuration (simulated)."""

from dataclasses import dataclass


@dataclass
class DatabaseConfig:
    """Simulated database connection settings."""
    host: str = "localhost"
    port: int = 5432
    database: str = "app_db"
    pool_size: int = 10

    def connection_string(self) -> str:
        """Build a connection string."""
        return f"db://{self.host}:{self.port}/{self.database}"
