"""Tests for AuthService business logic."""

import pytest
from app.services.auth_service import AuthService


class TestAuthServiceLoginUser:
    """Tests for AuthService.login_user."""

    def test_login_with_valid_credentials(self) -> None:
        svc = AuthService()
        result = svc.login_user("admin", "admin123")
        assert result["success"] is True
        assert result["token"] is not None

    def test_login_user_not_found(self) -> None:
        svc = AuthService()
        result = svc.login_user("ghost", "password")
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_login_wrong_password(self) -> None:
        svc = AuthService()
        result = svc.login_user("admin", "wrongpass")
        assert result["success"] is False
        assert "invalid" in result["error"]

    def test_logout_invalidates_token(self) -> None:
        svc = AuthService()
        result = svc.login_user("alice", "alice123")
        token = result["token"]
        svc.logout_user(token)
        check = svc.validate_session(token)
        assert check["valid"] is False

    def test_validate_session_returns_username(self) -> None:
        svc = AuthService()
        result = svc.login_user("bob", "bob123")
        check = svc.validate_session(result["token"])
        assert check["valid"] is True
        assert check["username"] == "bob"
