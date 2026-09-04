"""Small, dependency-free session authentication for the local Radar UI.

The password is supplied through the process environment and is never written
to the repository or to application logs. Sessions live only in memory, which
keeps the local tool simple and means a server restart invalidates all logins.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass


SESSION_COOKIE = "radar_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60


@dataclass(frozen=True)
class Session:
    username: str
    expires_at: float


_sessions: dict[str, Session] = {}
_failed_attempts: dict[str, tuple[int, float]] = {}


def auth_disabled() -> bool:
    return os.environ.get("RADAR_AUTH_DISABLED", "").strip().lower() in {"1", "true", "yes"}


def configured_username() -> str:
    return os.environ.get("RADAR_AUTH_USERNAME", "admin").strip() or "admin"


def configured_password() -> str:
    return os.environ.get("RADAR_AUTH_PASSWORD", "")


def setup_required() -> bool:
    return not auth_disabled() and not configured_password()


def _password_digest(password: str) -> bytes:
    # A fixed digest prevents timing differences from depending on password
    # length while keeping the clear-text secret out of comparison code.
    return hashlib.sha256(password.encode("utf-8")).digest()


def verify_credentials(username: str, password: str) -> bool:
    if auth_disabled() or setup_required():
        return False
    expected_user = configured_username().encode("utf-8")
    supplied_user = username.strip().encode("utf-8")
    return hmac.compare_digest(supplied_user, expected_user) and hmac.compare_digest(
        _password_digest(password), _password_digest(configured_password())
    )


def _prune(now: float) -> None:
    for token, session in list(_sessions.items()):
        if session.expires_at <= now:
            _sessions.pop(token, None)
    for address, (_count, until) in list(_failed_attempts.items()):
        if until and until <= now:
            _failed_attempts.pop(address, None)


def login_allowed(address: str, now: float | None = None) -> bool:
    current = time.time() if now is None else now
    _prune(current)
    attempt = _failed_attempts.get(address)
    return not attempt or not attempt[1] or attempt[1] <= current


def record_failed_login(address: str, now: float | None = None) -> None:
    current = time.time() if now is None else now
    count, _until = _failed_attempts.get(address, (0, current))
    count += 1
    lock_until = current + LOCKOUT_SECONDS if count >= MAX_LOGIN_ATTEMPTS else 0.0
    _failed_attempts[address] = (count, lock_until)


def create_session(username: str, now: float | None = None) -> tuple[str, int]:
    current = time.time() if now is None else now
    _prune(current)
    token = secrets.token_urlsafe(32)
    expires = int(current + SESSION_TTL_SECONDS)
    _sessions[token] = Session(username=username, expires_at=expires)
    return token, expires


def session_for(token: str | None, now: float | None = None) -> Session | None:
    if auth_disabled():
        return Session(configured_username(), float("inf"))
    if not token:
        return None
    current = time.time() if now is None else now
    _prune(current)
    session = _sessions.get(token)
    return session if session and session.expires_at > current else None


def delete_session(token: str | None) -> None:
    if token:
        _sessions.pop(token, None)


def parse_cookie(header: str | None, name: str = SESSION_COOKIE) -> str | None:
    if not header:
        return None
    for item in header.split(";"):
        key, separator, value = item.strip().partition("=")
        if separator and key == name:
            return value or None
    return None

