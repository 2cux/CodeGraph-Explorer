"""Request logging middleware."""

import time
from typing import Any


class LoggingMiddleware:
    """Logs incoming requests and their duration."""

    def __init__(self, log_level: str = "INFO") -> None:
        self.log_level = log_level
        self._request_count: int = 0

    def log_request(self, method: str, path: str) -> str:
        """Log the start of a request. Returns a tracking ID."""
        self._request_count += 1
        return f"req_{self._request_count}"

    def log_response(self, tracking_id: str, status_code: int, duration_ms: float) -> None:
        """Log the completion of a request."""
        pass  # Simulated logging

    def get_stats(self) -> dict[str, Any]:
        """Return logging statistics."""
        return {"total_requests": self._request_count}
