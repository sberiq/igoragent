from datetime import datetime, timedelta, timezone

from igoragent_core.memory import MemoryKind, MemoryScope, MemoryService, MemorySettings, memory_item


def settings(**changes: object) -> MemorySettings:
    values: dict[str, object] = {
        "enabled": True,
        "writes_paused": False,
        "max_items_per_scope": 2,
        "max_bytes_per_scope": 1_024,
        "max_retrieval_items": 2,
        "max_context_tokens": 128,
        "monthly_write_token_budget": 100,
    }
    values.update(changes)
    return MemorySettings(**values)


def test_memory_rejects_secrets_and_low_confidence() -> None:
    service = MemoryService(settings())
    scope = MemoryScope(owner_id=1, user_id=2)
    assert service.add(memory_item(scope, MemoryKind.FACT, "api_key=secret", 0.9, 30)) is None
    assert service.add(memory_item(scope, MemoryKind.FACT, "user likes tea", 0.5, 30)) is None
    assert service.stats(scope).rejected_count == 2


def test_memory_deduplicates_items_within_scope() -> None:
    service = MemoryService(settings())
    scope = MemoryScope(owner_id=1, user_id=2)
    first = service.add(memory_item(scope, MemoryKind.PREFERENCE, "User likes dark tea", 0.8, 30))
    second = service.add(memory_item(scope, MemoryKind.PREFERENCE, " user   likes DARK tea ", 0.9, 30))
    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert service.stats(scope).item_count == 1


def test_memory_evicts_oldest_low_confidence_item() -> None:
    service = MemoryService(settings(max_items_per_scope=2))
    scope = MemoryScope(owner_id=1, user_id=2)
    first = service.add(memory_item(scope, MemoryKind.FACT, "first memory", 0.76, 30))
    service.add(memory_item(scope, MemoryKind.FACT, "second memory", 0.85, 30))
    service.add(memory_item(scope, MemoryKind.FACT, "third memory", 0.95, 30))
    assert first is not None
    assert service.stats(scope).item_count == 2
    assert not service.delete(first.id, scope)


def test_memory_retrieval_stays_inside_token_budget() -> None:
    service = MemoryService(settings(max_context_tokens=128, max_retrieval_items=8))
    scope = MemoryScope(owner_id=1, user_id=2)
    service.add(memory_item(scope, MemoryKind.FACT, "User likes tea", 0.9, 30))
    service.add(memory_item(scope, MemoryKind.FACT, "User likes " + "very detailed novels " * 40, 0.9, 30))
    results = service.retrieve(scope, "what does user like")
    assert sum(item.token_estimate for item in results) <= 128


def test_memory_expiry_and_scope_forget() -> None:
    service = MemoryService(settings())
    scope = MemoryScope(owner_id=1, user_id=2, chat_id=3)
    expired = memory_item(scope, MemoryKind.FACT, "old memory", 0.9, 30)
    expired.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert service.add(expired) is None
    service.add(memory_item(scope, MemoryKind.FACT, "forget me", 0.9, 30))
    assert service.forget_scope(scope) == 1
    assert service.stats(scope).item_count == 0
