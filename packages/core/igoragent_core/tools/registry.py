from __future__ import annotations

from hashlib import sha256
from typing import Any

from pydantic import BaseModel, HttpUrl


class CaptionedMediaRequest(BaseModel):
    target_chat_id: int
    source_url: HttpUrl
    caption: str = ""
    idempotency_key: str

    def content_hash(self) -> str:
        data = f"{self.target_chat_id}|{self.source_url}|{self.caption}|{self.idempotency_key}"
        return sha256(data.encode()).hexdigest()


class ToolResult(BaseModel):
    ok: bool
    detail: str
    data: dict[str, Any] = {}


class ToolRegistry:
    """Explicit registry; tools stay unavailable until registered and policy-approved."""

    def __init__(self) -> None:
        self._results: dict[str, ToolResult] = {}

    def record(self, key: str, result: ToolResult) -> ToolResult:
        self._results[key] = result
        return result

    def prior_result(self, key: str) -> ToolResult | None:
        return self._results.get(key)
