"""Tests for utility functions."""

from app.utils.hash import hash_password, verify_password
from app.utils.validation import validate_email, validate_username, validate_password_strength


class TestHashUtils:
    """Tests for password hashing utilities."""

    def test_hash_and_verify(self) -> None:
        hashed = hash_password("secret")
        assert verify_password("secret", hashed) is True

    def test_verify_wrong_password(self) -> None:
        hashed = hash_password("secret")
        assert verify_password("wrong", hashed) is False


class TestValidation:
    """Tests for input validation utilities."""

    def test_valid_email(self) -> None:
        assert validate_email("user@example.com") is True

    def test_invalid_email(self) -> None:
        assert validate_email("not-an-email") is False

    def test_valid_username(self) -> None:
        assert validate_username("john_doe") is None

    def test_short_username(self) -> None:
        err = validate_username("ab")
        assert err is not None and "at least 3" in err

    def test_weak_password(self) -> None:
        err = validate_password_strength("short")
        assert err is not None
