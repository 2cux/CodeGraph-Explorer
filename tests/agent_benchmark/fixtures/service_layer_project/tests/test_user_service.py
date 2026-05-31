"""Tests for UserService CRUD operations."""

import pytest
from app.services.user_service import UserService
from app.models.user import UserCreateRequest


class TestUserService:
    """Test suite for UserService."""

    def test_create_user(self) -> None:
        svc = UserService()
        req = UserCreateRequest(
            username="charlie",
            email="charlie@example.com",
            password="charlie123",
        )
        resp = svc.create_user(req)
        assert resp.username == "charlie"
        assert resp.email == "charlie@example.com"

    def test_get_user_not_found(self) -> None:
        svc = UserService()
        with pytest.raises(ValueError, match="not found"):
            svc.get_user(999)

    def test_delete_user(self) -> None:
        svc = UserService()
        req = UserCreateRequest(
            username="to_delete",
            email="del@example.com",
            password="del123",
        )
        resp = svc.create_user(req)
        assert svc.delete_user(resp.id) is True
