from __future__ import annotations
from typing import Optional
"""
Stateless HMAC session tokens for /chat authentication.
Token format: base64url(user_id:issued_at):HMAC-SHA256(payload, AUTH_SECRET_KEY)
Tokens expire after TOKEN_TTL_SECONDS (24 h by default).
No database required — the signature is the proof of identity.
"""

import base64
import hashlib
import hmac
import time
from fastapi import Header, HTTPException

from app.config import get_settings

TOKEN_TTL_SECONDS = 86_400  # 24 hours


def _sign(payload: str, secret: str) -> str:
    return hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()


def generate_token(user_id: str) -> str:
    issued_at = str(int(time.time()))
    raw = f"{user_id}:{issued_at}"
    payload_b64 = base64.urlsafe_b64encode(raw.encode()).decode()
    sig = _sign(payload_b64, get_settings().AUTH_SECRET_KEY)
    return f"{payload_b64}.{sig}"


def validate_token(token: str) -> str:
    """Returns user_id or raises HTTPException(401)."""
    try:
        payload_b64, sig = token.rsplit(".", 1)
    except ValueError:
        raise HTTPException(401, "Invalid token format")

    expected_sig = _sign(payload_b64, get_settings().AUTH_SECRET_KEY)
    if not hmac.compare_digest(expected_sig, sig):
        raise HTTPException(401, "Token signature invalid")

    try:
        raw = base64.urlsafe_b64decode(payload_b64.encode()).decode()
        user_id, issued_at_str = raw.split(":", 1)
    except Exception:
        raise HTTPException(401, "Token payload corrupt")

    age = time.time() - float(issued_at_str)
    if age > TOKEN_TTL_SECONDS:
        raise HTTPException(401, "Token expired")

    return user_id


def get_current_user(x_auth_token: Optional[str] = Header(default=None)) -> Optional[str]:
    """FastAPI dependency — returns user_id if a valid token is present, else None."""
    if x_auth_token is None:
        return None
    return validate_token(x_auth_token)
