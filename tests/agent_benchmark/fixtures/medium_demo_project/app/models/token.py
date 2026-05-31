"""Token model for session tracking."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SessionToken:
    """Represents an active authentication session."""
    token: str
    username: str
    created_at: float
    expires_at: Optional[float] = None

    def is_expired(self) -> bool:
        """Check if this session token has expired."""
        if self.expires_at is None:
            return False
        import time
        return time.time() > self.expires_at
