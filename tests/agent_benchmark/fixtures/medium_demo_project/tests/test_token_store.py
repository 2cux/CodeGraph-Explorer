"""Tests for the token store module."""

import pytest
from app.store.token_store import TokenStore


class TestTokenStore:
    """Tests for TokenStore operations."""

    def test_save_and_validate(self) -> None:
        store = TokenStore()
        token = store.save_token("alice")
        assert store.validate_token(token) == "alice"

    def test_revoke_token(self) -> None:
        store = TokenStore()
        token = store.save_token("bob")
        store.revoke_token(token)
        assert store.validate_token(token) is None

    def test_revoke_all_for_user(self) -> None:
        store = TokenStore()
        store.save_token("carol")
        store.save_token("carol")
        store.save_token("dave")
        revoked = store.revoke_all_for_user("carol")
        assert revoked == 2

    def test_list_sessions(self) -> None:
        store = TokenStore()
        store.save_token("eve")
        sessions = store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["username"] == "eve"

    def test_mfa_pending_session(self) -> None:
        store = TokenStore()
        sid = store.create_pending_session("frank")
        assert store.get_pending_username(sid) == "frank"
        store.remove_pending_session(sid)
        assert store.get_pending_username(sid) is None
