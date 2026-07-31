from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path


class TelegramAuthError(Exception):
    pass


@dataclass
class PendingLogin:
    api_id: int
    api_hash: str
    phone_number: str
    client: object
    phone_code_hash: str


class TelegramLoginService:
    """Short-lived login state. API credentials and codes are never persisted or returned."""

    def __init__(self) -> None:
        self._pending: PendingLogin | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._pending is None and self._session_exists()

    async def begin(self, api_id: int, api_hash: str, phone_number: str) -> None:
        async with self._lock:
            await self._disconnect_pending()
            try:
                from telethon import TelegramClient
            except ImportError as error:
                raise TelegramAuthError("Telethon is not installed") from error

            session_path = self._session_path()
            session_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            client = TelegramClient(str(session_path), api_id, api_hash)
            await client.connect()
            result = await client.send_code_request(phone_number)
            self._pending = PendingLogin(api_id, api_hash, phone_number, client, result.phone_code_hash)

    async def complete(self, code: str, password: str | None = None) -> int:
        async with self._lock:
            if self._pending is None:
                raise TelegramAuthError("No Telegram login is awaiting a code")
            pending = self._pending
            try:
                await pending.client.sign_in(
                    phone=pending.phone_number,
                    code=code,
                    phone_code_hash=pending.phone_code_hash,
                )
            except Exception as error:
                if error.__class__.__name__ == "SessionPasswordNeededError":
                    if not password:
                        raise TelegramAuthError("Two-factor password is required") from error
                    await pending.client.sign_in(password=password)
                else:
                    raise TelegramAuthError("Telegram rejected the login code") from error
            me = await pending.client.get_me()
            await pending.client.disconnect()
            self._pending = None
            self._harden_session_permissions()
            return int(me.id)

    async def cancel(self) -> None:
        async with self._lock:
            await self._disconnect_pending()

    async def _disconnect_pending(self) -> None:
        if self._pending is not None:
            await self._pending.client.disconnect()
            self._pending = None

    def _session_path(self) -> Path:
        return Path(os.getenv("TELEGRAM_SESSION_PATH", ".data/telegram.session"))

    def _session_exists(self) -> bool:
        path = self._session_path()
        return path.exists() or path.with_suffix(path.suffix + "-journal").exists()

    def _harden_session_permissions(self) -> None:
        for path in (self._session_path(), self._session_path().with_suffix(self._session_path().suffix + "-journal")):
            if path.exists():
                path.chmod(0o600)
