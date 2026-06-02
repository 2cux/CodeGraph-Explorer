"""Factory module — calls PascalCase constructors."""

from constructors.models import User, TokenStore


def create_user(name: str) -> User:
    """Create a user — calls User() constructor."""
    user = User(name)  # PascalCase constructor — should NOT be silently dropped
    return user


def setup_token_store() -> TokenStore:
    """Set up token store — calls TokenStore() constructor."""
    store = TokenStore()  # PascalCase constructor — should NOT be silently dropped
    return store


def create_and_save(name: str) -> None:
    """Create user and save — constructor chain."""
    User(name).save()  # Constructor chain — should generate both edges
