"""MFA service — TOTP generation and verification."""

import hashlib
import hmac
import time


class MfaService:
    """Handles TOTP-based multi-factor authentication."""

    def generate_secret(self) -> str:
        """Generate a new TOTP secret for a user."""
        import secrets
        return secrets.token_hex(16)

    def verify_code(self, secret: str, code: str) -> bool:
        """Verify a TOTP code against the user's secret."""
        if secret is None:
            return False
        expected = self._compute_totp(secret)
        return hmac.compare_digest(expected, code)

    def _compute_totp(self, secret: str) -> str:
        """Compute the current TOTP value."""
        counter = int(time.time() // 30)
        mac = hmac.new(
            secret.encode(), counter.to_bytes(8, "big"), hashlib.sha256
        )
        return mac.hexdigest()[:6]
