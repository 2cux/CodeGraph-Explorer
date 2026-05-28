"""MFA / TOTP generation and verification using only Python standard library.

Implements RFC 6238 TOTP with HMAC-SHA1, 30-second time step, 6-digit codes,
and +/-1 window tolerance.

NOTE: Python 3.6 compatible (no ``X | Y`` union syntax, no ``dataclasses``).
"""

import base64
import hashlib
import hmac
import struct
import time
from typing import Optional


def _decode_secret(secret: str) -> bytes:
    """Decode a base32-encoded TOTP secret into raw bytes."""
    cleaned = secret.upper().replace(" ", "")
    pad = 8 - (len(cleaned) % 8)
    if pad != 8:
        cleaned += "=" * pad
    return base64.b32decode(cleaned)


def generate_totp(secret: str, timestamp: Optional[int] = None) -> str:
    """Generate a 6-digit TOTP code.

    Args:
        secret: Base32-encoded shared secret.
        timestamp: Unix timestamp (defaults to current time).

    Returns:
        6-digit code as a zero-padded string.
    """
    if timestamp is None:
        timestamp = int(time.time())
    counter = timestamp // 30
    counter_bytes = struct.pack(">Q", counter)
    key = _decode_secret(secret)
    digest = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return "{:06d}".format(truncated % 1_000_000)


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code with +/-1 time-step window tolerance.

    Args:
        secret: Base32-encoded shared secret.
        code: The 6-digit code to verify.

    Returns:
        True if the code matches within the time window.
    """
    now = int(time.time())
    for delta in range(-1, 2):
        if generate_totp(secret, now + delta * 30) == code:
            return True
    return False
