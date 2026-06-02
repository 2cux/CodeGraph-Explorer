"""Tests for import alias resolution."""

from constructors.models import User as UserModel
from constructors.models import TokenStore as TokenRepo


def create_with_alias(name: str) -> UserModel:
    """Create user using imported alias."""
    user = UserModel(name)  # alias import — should resolve to constructors.models.User
    return user


def use_token_repo() -> None:
    """Use token repository via alias."""
    repo = TokenRepo()  # alias import — should resolve to constructors.models.TokenStore
    repo.store_token("abc")
