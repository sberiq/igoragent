from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


@dataclass
class Session:
    session_id: str
    csrf_token: str
    expires_at: datetime


class AuthService:
    def __init__(self) -> None:
        self._hasher = PasswordHasher()
        self._password_hash: str | None = None
        self._sessions: dict[str, Session] = {}
        self._attempts: dict[str, list[datetime]] = {}
        self._lock = Lock()

    @property
    def configured(self) -> bool:
        return self._password_hash is not None

    def set_initial_password(self, password: str, confirmation: str) -> None:
        if self.configured:
            raise ValueError("Password is already configured")
        if password != confirmation:
            raise ValueError("Passwords do not match")
        if len(password) < 14 or password.casefold() in {"password", "igoragent", "12345678901234"}:
            raise ValueError("Use a unique password with at least 14 characters")
        self._password_hash = self._hasher.hash(password)

    def login(self, password: str, client_key: str) -> Session | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            attempts = [time for time in self._attempts.get(client_key, []) if now - time < timedelta(minutes=15)]
            if len(attempts) >= 5:
                self._attempts[client_key] = attempts
                return None
            if self._password_hash is None:
                return None
            try:
                valid = self._hasher.verify(self._password_hash, password)
            except VerifyMismatchError:
                valid = False
            if not valid:
                attempts.append(now)
                self._attempts[client_key] = attempts
                return None
            self._attempts.pop(client_key, None)
            session = Session(
                session_id=secrets.token_urlsafe(32),
                csrf_token=secrets.token_urlsafe(32),
                expires_at=now + timedelta(hours=8),
            )
            self._sessions[session.session_id] = session
            return session

    def authenticate(self, session_id: str | None, csrf_token: str | None, state_change: bool) -> bool:
        if not session_id:
            return False
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.expires_at <= datetime.now(timezone.utc):
                self._sessions.pop(session_id, None)
                return False
            return not state_change or bool(csrf_token and secrets.compare_digest(session.csrf_token, csrf_token))

    def logout(self, session_id: str | None) -> None:
        if session_id:
            with self._lock:
                self._sessions.pop(session_id, None)

    def restore_password_hash(self, password_hash: str | None) -> None:
        self._password_hash = password_hash

    def exported_password_hash(self) -> str | None:
        return self._password_hash

    def password_fingerprint(self) -> str | None:
        if self._password_hash is None:
            return None
        return sha256(self._password_hash.encode()).hexdigest()
