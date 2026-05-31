"""Password hashing utility."""

import hashlib


def hash_password(password: str, salt: str = "") -> str:
    """Hash a password with optional salt."""
    data = (password + salt).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def verify_password(password: str, hashed: str, salt: str = "") -> bool:
    """Verify a password against a hash."""
    return hash_password(password, salt) == hashed


def generate_salt() -> str:
    """Generate a random salt string."""
    import secrets
    return secrets.token_hex(8)
