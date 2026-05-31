"""Tests for the UserService business logic."""

import pytest
from app.services.user_service import UserService
from app.models.user import Role
from app.store.user_store import UserStore


class TestUserService:
    """Tests for UserService CRUD and search."""

    def test_register_user(self) -> None:
        svc = UserService()
        result = svc.register_user("newuser", "new@example.com", "Pass1234", Role.member)
        assert result["success"] is True
        assert result["user_id"] is not None

    def test_register_duplicate_username(self) -> None:
        svc = UserService()
        svc.register_user("dup", "a@b.com", "Pass1234", Role.member)
        result = svc.register_user("dup", "c@d.com", "Pass1234", Role.member)
        assert result["success"] is False
        assert "taken" in result["error"]

    def test_get_profile_not_found(self) -> None:
        svc = UserService()
        result = svc.get_profile(99999)
        assert result["success"] is False

    def test_search_users(self) -> None:
        svc = UserService()
        svc.register_user("searchme", "sm@example.com", "Pass1234", Role.member)
        results = svc.search("search")
        assert len(results) >= 1
