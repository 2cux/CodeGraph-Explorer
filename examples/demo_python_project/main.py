"""Demo project entry point."""

from app.api.auth import login, logout
from app.api.users import get_users


def main() -> None:
    users = get_users()
    for user in users:
        token = login(user["name"], "password123")
        print(f"Logged in: {token}")
        logout(token)


if __name__ == "__main__":
    main()
