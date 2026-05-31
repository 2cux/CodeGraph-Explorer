"""Tests for the authentication module."""

import pytest
from app.api.auth import login, logout
from app.store.token_store import TokenStore


class TestAuthLogin:
    """Tests for the login function."""

    def test_login_success(self) -> None:
        """Login with valid credentials returns a token."""
        result = login("admin", "admin123")
        assert result["success"] is True
        assert result["token"] is not None

    def test_login_user_not_found(self) -> None:
        """Login with unknown username returns error."""
        result = login("nobody", "password")
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_login_wrong_password(self) -> None:
        """Login with wrong password returns error."""
        result = login("admin", "wrong")
        assert result["success"] is False
        assert "invalid password" in result["error"]

    def test_logout_revokes_token(self) -> None:
        """Logout should invalidate the session token."""
        result = login("alice", "alice123")
        assert result["success"] is True
        token = result["token"]
        logout(token)
        store = TokenStore()
        assert store.validate_token(token) is None


class TestTokenStore:
    """Tests for the TokenStore class."""

    def test_save_and_validate(self) -> None:
        store = TokenStore()
        token = store.save_token("alice")
        assert store.validate_token(token) == "alice"

    def test_revoke_removes_token(self) -> None:
        store = TokenStore()
        token = store.save_token("bob")
        store.revoke_token(token)
        assert store.validate_token(token) is None

    def test_count_sessions(self) -> None:
        store = TokenStore()
        store.save_token("user_a")
        store.save_token("user_b")
        assert store.count_sessions() == 2
