from igoragent_core.policy_engine import (
    AccessMode,
    Action,
    Actor,
    AgentPolicy,
    ChannelAccess,
    PolicyEngine,
    ToolPermission,
)


def test_group_messages_need_mention_by_default() -> None:
    engine = PolicyEngine(AgentPolicy(group_access=AccessMode.ALL))
    decision = engine.can_receive(Actor(telegram_id=10), -100, ChannelAccess.GROUP)
    assert not decision.allowed
    assert decision.reason == "group requires mention or reply"


def test_admin_bypasses_chat_allowlist() -> None:
    engine = PolicyEngine(AgentPolicy(admin_telegram_ids={1}))
    decision = engine.can_receive(Actor(telegram_id=1), -999, ChannelAccess.GROUP)
    assert decision.allowed
    assert decision.reason == "administrator"


def test_captioned_media_is_admin_only_by_default() -> None:
    engine = PolicyEngine(AgentPolicy(group_access=AccessMode.ALL, admin_telegram_ids={1}))
    user = engine.can_execute(Actor(telegram_id=2), Action.SEND_CAPTIONED_MEDIA, -10, ChannelAccess.GROUP)
    admin = engine.can_execute(Actor(telegram_id=1), Action.SEND_CAPTIONED_MEDIA, -10, ChannelAccess.GROUP)
    assert not user.allowed
    assert admin.allowed


def test_captioned_media_can_be_granted_to_allowed_users() -> None:
    engine = PolicyEngine(AgentPolicy(
        group_access=AccessMode.ALL,
        tool_permissions={Action.SEND_CAPTIONED_MEDIA: ToolPermission.ALLOWED_USERS},
    ))
    decision = engine.can_execute(Actor(telegram_id=2), Action.SEND_CAPTIONED_MEDIA, -10, ChannelAccess.GROUP)
    assert decision.allowed
