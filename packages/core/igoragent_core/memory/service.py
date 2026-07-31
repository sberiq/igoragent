from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from hashlib import sha256
import math
import re
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    SUMMARY = "summary"


class MemoryScope(BaseModel):
    owner_id: int = Field(gt=0)
    user_id: int | None = None
    chat_id: int | None = None

    def key(self) -> tuple[int, int | None, int | None]:
        return self.owner_id, self.user_id, self.chat_id


class MemorySettings(BaseModel):
    enabled: bool = False
    writes_paused: bool = True
    max_items_per_scope: int = Field(default=100, ge=1, le=1_000)
    max_bytes_per_scope: int = Field(default=256 * 1024, ge=1_024, le=10 * 1024 * 1024)
    retention_days: int = Field(default=30, ge=1, le=365)
    max_retrieval_items: int = Field(default=8, ge=1, le=32)
    max_context_tokens: int = Field(default=1_500, ge=128, le=8_000)
    monthly_write_token_budget: int = Field(default=20_000, ge=0, le=2_000_000)
    min_confidence: float = Field(default=0.75, ge=0, le=1)
    filter_sensitive_content: bool = True


class MemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    scope: MemoryScope
    kind: MemoryKind
    text: str = Field(min_length=1, max_length=16_384)
    confidence: float = Field(ge=0, le=1)
    source: str = Field(default="conversation", max_length=128)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    pinned: bool = False
    normalized_hash: str = ""
    byte_size: int = 0
    token_estimate: int = 0

    @field_validator("text")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    def finalize(self) -> "MemoryItem":
        normalized = normalize_memory_text(self.text)
        self.normalized_hash = sha256(normalized.encode()).hexdigest()
        self.byte_size = len(self.text.encode())
        self.token_estimate = estimate_tokens(self.text)
        return self


class MemoryStats(BaseModel):
    item_count: int = 0
    byte_count: int = 0
    token_count: int = 0
    evicted_count: int = 0
    rejected_count: int = 0


SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:api[_ -]?key|authorization|bearer|password|passcode|session(?:[_ -]?string)?|private[_ -]?key)\s*[:=]\s*\S+", re.I),
    re.compile(r"\b\d{5,8}\b.*\b(?:code|otp|2fa|verification)\b|\b(?:code|otp|2fa|verification)\b.*\b\d{5,8}\b", re.I),
    re.compile(r"\b(?:seed phrase|mnemonic|wallet key)\b", re.I),
    re.compile(r"(?i)ignore (?:all |previous |the )?(?:instructions|rules)|system prompt|developer message"),
)
HIGH_ENTROPY_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")


def normalize_memory_text(text: str) -> str:
    return " ".join(text.casefold().split())


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text.encode()) / 4))


def contains_sensitive_content(text: str) -> bool:
    return any(pattern.search(text) for pattern in SENSITIVE_PATTERNS) or bool(HIGH_ENTROPY_TOKEN.search(text))


class MemoryService:
    """Bounded in-process repository; replace with PostgreSQL repository in production."""

    def __init__(self, settings: MemorySettings | None = None) -> None:
        self.settings = settings or MemorySettings()
        self._items: dict[str, MemoryItem] = {}
        self._monthly_written_tokens: dict[tuple[int, int, int], int] = {}
        self._evicted_count = 0
        self._rejected_count = 0

    def add(self, item: MemoryItem, now: datetime | None = None) -> MemoryItem | None:
        now = now or datetime.now(timezone.utc)
        if not self.settings.enabled or self.settings.writes_paused:
            self._rejected_count += 1
            return None
        item.finalize()
        if item.confidence < self.settings.min_confidence:
            self._rejected_count += 1
            return None
        if self.settings.filter_sensitive_content and contains_sensitive_content(item.text):
            self._rejected_count += 1
            return None
        if item.expires_at <= now:
            self._rejected_count += 1
            return None

        month_key = (item.scope.owner_id, now.year, now.month)
        used = self._monthly_written_tokens.get(month_key, 0)
        if used + item.token_estimate > self.settings.monthly_write_token_budget:
            self._rejected_count += 1
            return None

        duplicate = self._find_duplicate(item)
        if duplicate:
            duplicate.updated_at = now
            duplicate.last_accessed_at = now
            duplicate.confidence = max(duplicate.confidence, item.confidence)
            return duplicate

        self._items[item.id] = item
        self._monthly_written_tokens[month_key] = used + item.token_estimate
        self.evict(item.scope, now)
        return self._items.get(item.id)

    def retrieve(self, scope: MemoryScope, query: str, now: datetime | None = None) -> list[MemoryItem]:
        now = now or datetime.now(timezone.utc)
        self.evict(scope, now)
        terms = set(normalize_memory_text(query).split())
        candidates = [item for item in self._items.values() if item.scope.key() == scope.key() and item.expires_at > now]
        ranked = sorted(candidates, key=lambda item: self._score(item, terms, now), reverse=True)
        output: list[MemoryItem] = []
        used_tokens = 0
        for item in ranked:
            if len(output) >= self.settings.max_retrieval_items:
                break
            if used_tokens + item.token_estimate > self.settings.max_context_tokens:
                continue
            item.last_accessed_at = now
            output.append(item)
            used_tokens += item.token_estimate
        return output

    def delete(self, item_id: str, scope: MemoryScope) -> bool:
        item = self._items.get(item_id)
        if item is None or item.scope.key() != scope.key():
            return False
        del self._items[item_id]
        return True

    def forget_scope(self, scope: MemoryScope) -> int:
        item_ids = [item.id for item in self._items.values() if item.scope.key() == scope.key()]
        for item_id in item_ids:
            del self._items[item_id]
        return len(item_ids)

    def stats(self, scope: MemoryScope | None = None) -> MemoryStats:
        items = list(self._items.values())
        if scope:
            items = [item for item in items if item.scope.key() == scope.key()]
        return MemoryStats(
            item_count=len(items),
            byte_count=sum(item.byte_size for item in items),
            token_count=sum(item.token_estimate for item in items),
            evicted_count=self._evicted_count,
            rejected_count=self._rejected_count,
        )

    def evict(self, scope: MemoryScope, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        scoped = [item for item in self._items.values() if item.scope.key() == scope.key()]
        for item in scoped:
            if item.expires_at <= now and not item.pinned:
                del self._items[item.id]
                self._evicted_count += 1
        scoped = [item for item in self._items.values() if item.scope.key() == scope.key()]
        def over_limit() -> bool:
            return len(scoped) > self.settings.max_items_per_scope or sum(item.byte_size for item in scoped) > self.settings.max_bytes_per_scope
        while over_limit():
            candidates = [item for item in scoped if not item.pinned]
            if not candidates:
                break
            victim = min(candidates, key=lambda item: (item.confidence, item.last_accessed_at, item.created_at))
            del self._items[victim.id]
            scoped.remove(victim)
            self._evicted_count += 1

    def _find_duplicate(self, candidate: MemoryItem) -> MemoryItem | None:
        return next((item for item in self._items.values() if item.scope.key() == candidate.scope.key() and item.normalized_hash == candidate.normalized_hash), None)

    def _score(self, item: MemoryItem, terms: set[str], now: datetime) -> float:
        text_terms = set(normalize_memory_text(item.text).split())
        lexical = len(terms & text_terms) / max(1, len(terms))
        age_days = max(0, (now - item.updated_at).total_seconds() / 86_400)
        recency = math.exp(-age_days / 30)
        return lexical * 0.65 + item.confidence * 0.25 + recency * 0.1


def memory_item(scope: MemoryScope, kind: MemoryKind, text: str, confidence: float, retention_days: int, source: str = "conversation") -> MemoryItem:
    now = datetime.now(timezone.utc)
    return MemoryItem(scope=scope, kind=kind, text=text, confidence=confidence, source=source, expires_at=now + timedelta(days=retention_days))
