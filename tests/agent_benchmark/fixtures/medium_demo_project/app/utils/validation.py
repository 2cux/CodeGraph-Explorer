"""Input validation utilities."""

import re
from typing import Optional


def validate_email(email: str) -> bool:
    """Check if an email address is well-formed."""
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email))


def validate_username(username: str) -> Optional[str]:
    """Validate username format. Returns error message or None."""
    if len(username) < 3:
        return "username must be at least 3 characters"
    if len(username) > 32:
        return "username must be at most 32 characters"
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", username):
        return "username must start with a letter and contain only letters, digits, underscores"
    return None


def validate_password_strength(password: str, min_length: int = 8) -> Optional[str]:
    """Validate password meets strength requirements. Returns error or None."""
    if len(password) < min_length:
        return f"password must be at least {min_length} characters"
    if not re.search(r"[A-Z]", password):
        return "password must contain an uppercase letter"
    if not re.search(r"[0-9]", password):
        return "password must contain a digit"
    return None
