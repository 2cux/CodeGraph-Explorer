"""Application entry point — initializes stores with seed data."""

from app.store.user_store import UserStore
from app.models.user import User, Role


def main() -> None:
    """Seed the user store with default test users."""
    store = UserStore()

    admin = User(username="admin", email="admin@example.com", role=Role.admin,
                 mfa_enabled=True, mfa_secret="admin_secret_key")
    admin.set_password("admin123")
    store.insert(admin)

    alice = User(username="alice", email="alice@example.com", role=Role.member)
    alice.set_password("alice123")
    store.insert(alice)

    bob = User(username="bob", email="bob@example.com", role=Role.viewer)
    bob.set_password("bob123")
    store.insert(bob)


if __name__ == "__main__":
    main()
