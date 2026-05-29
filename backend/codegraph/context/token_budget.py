"""Token budget tracking and estimation for Context Pack generation.

Provides a lightweight TokenBudget class and a standalone estimate_tokens()
function. Uses a simple char/4 heuristic that can be replaced with tiktoken
later without changing the consumer API.
"""


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length using a rough heuristic.

    Returns at least 1 for any non-empty text, 0 for empty.
    """
    if not text:
        return 0
    return max(len(text) // 4, 1)


class TokenBudget:
    """Tracks token usage against a maximum budget."""

    def __init__(self, max_tokens: int) -> None:
        self.max_tokens = max_tokens
        self.used: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used)

    def can_fit(self, estimated_tokens: int, priority: str = "medium") -> bool:
        """Check whether *estimated_tokens* fit within the remaining budget.

        Critical and high-priority items always report as fitting — they
        will be degraded rather than dropped.
        """
        if priority in ("critical", "high"):
            return True
        return self.used + estimated_tokens <= self.max_tokens

    def spend(self, estimated_tokens: int) -> None:
        """Record token usage."""
        self.used += estimated_tokens

    def as_dict(self) -> dict[str, int]:
        return {
            "max_tokens": self.max_tokens,
            "used_tokens": self.used,
            "remaining": self.remaining,
        }
