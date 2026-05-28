"""Demo project entry point -- demonstrates login with and without MFA."""

from app.api.auth import login, logout, verify_mfa
from app.api.mfa import generate_totp
from app.api.users import get_users


def main() -> None:
    users = get_users()
    for user in users:
        print(f"\n--- Logging in as {user.name} (role={user.role}) ---")

        result = login(user.name, "password123")
        if not result.success:
            print(f"  Login failed: {result.error}")
            continue

        if result.session_id:
            # MFA is enabled -- simulate the TOTP code the user would
            # read from their authenticator app.
            assert user.mfa_secret is not None
            code = generate_totp(user.mfa_secret)
            print(f"  MFA challenge required.  Generated TOTP code: {code}")

            result = verify_mfa(result.session_id, code)
            if not result.success:
                print(f"  MFA verification failed: {result.error}")
                continue

        print(f"  Logged in successfully.  Token: {result.token}")
        logout(result.token)
        print("  Logged out.")


if __name__ == "__main__":
    main()
