from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, Field, model_validator


class AccessMode(StrEnum):
    ALL = "all"
    WHITELIST = "whitelist"
    ADMIN_ONLY = "admin_only"


class ActivationMode(StrEnum):
    MENTION_OR_REPLY = "mention_or_reply"
    ALL_MESSAGES = "all_messages"


class ToolPermission(StrEnum):
    DISABLED = "disabled"
    ALLOWED_USERS = "allowed_users"
    ADMIN_ONLY = "admin_only"


class ActorRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    USER = "user"


class ChannelAccess(StrEnum):
    DIRECT = "direct"
    GROUP = "group"
    CHANNEL = "channel"


class Action(StrEnum):
    RESPOND = "respond"
    SEND_TEXT = "send_text"
    SEND_CAPTIONED_MEDIA = "send_captioned_media"
    REACT = "react"
    EDIT_MESSAGE = "edit_message"
    DELETE_MESSAGE = "delete_message"
    CLICK_INLINE_BUTTON = "click_inline_button"
    OPEN_DEEP_LINK = "open_deep_link"
    CHANGE_AVATAR = "change_avatar"


class Actor(BaseModel):
    telegram_id: int
    role: ActorRole = ActorRole.USER


class AgentPolicy(BaseModel):
    admin_telegram_ids: set[int] = Field(default_factory=set)
    direct_access: AccessMode = AccessMode.ALL
    group_access: AccessMode = AccessMode.WHITELIST
    channel_access: AccessMode = AccessMode.WHITELIST
    group_activation: ActivationMode = ActivationMode.MENTION_OR_REPLY
    allowed_direct_ids: set[int] = Field(default_factory=set)
    allowed_group_ids: set[int] = Field(default_factory=set)
    allowed_channel_ids: set[int] = Field(default_factory=set)
    tool_permissions: dict[Action, ToolPermission] = Field(
        default_factory=lambda: {
            Action.SEND_TEXT: ToolPermission.ALLOWED_USERS,
            Action.SEND_CAPTIONED_MEDIA: ToolPermission.ADMIN_ONLY,
            Action.REACT: ToolPermission.ALLOWED_USERS,
            Action.EDIT_MESSAGE: ToolPermission.ADMIN_ONLY,
            Action.DELETE_MESSAGE: ToolPermission.ADMIN_ONLY,
            Action.CLICK_INLINE_BUTTON: ToolPermission.ADMIN_ONLY,
            Action.OPEN_DEEP_LINK: ToolPermission.ADMIN_ONLY,
            Action.CHANGE_AVATAR: ToolPermission.ADMIN_ONLY,
        }
    )

    @model_validator(mode="after")
    def validate_tool_permissions(self) -> "AgentPolicy":
        if Action.SEND_CAPTIONED_MEDIA not in self.tool_permissions:
            self.tool_permissions[Action.SEND_CAPTIONED_MEDIA] = ToolPermission.DISABLED
        return self


class Decision(BaseModel):
    allowed: bool
    reason: str
    requires_approval: bool = False


class PolicyEngine:
    def __init__(self, policy: AgentPolicy):
        self.policy = policy

    def can_receive(
        self,
        actor: Actor,
        chat_id: int,
        channel: ChannelAccess,
        mentioned: bool = False,
        reply_to_agent: bool = False,
    ) -> Decision:
        if self._is_admin(actor):
            return Decision(allowed=True, reason="administrator")

        mode, whitelist = self._access_rule(channel)
        if mode is AccessMode.ADMIN_ONLY:
            return Decision(allowed=False, reason="administrator-only access")
        if mode is AccessMode.WHITELIST and chat_id not in whitelist:
            return Decision(allowed=False, reason="chat is not allowlisted")

        if channel is ChannelAccess.GROUP and self.policy.group_activation is ActivationMode.MENTION_OR_REPLY:
            if not mentioned and not reply_to_agent:
                return Decision(allowed=False, reason="group requires mention or reply")
        return Decision(allowed=True, reason="inbound policy matched")

    def can_execute(
        self,
        actor: Actor,
        action: Action,
        chat_id: int,
        channel: ChannelAccess,
    ) -> Decision:
        inbound = self.can_receive(actor, chat_id, channel, mentioned=True)
        if not inbound.allowed:
            return inbound

        permission = self.policy.tool_permissions.get(action, ToolPermission.DISABLED)
        if permission is ToolPermission.DISABLED:
            return Decision(allowed=False, reason=f"{action.value} is disabled")
        if permission is ToolPermission.ADMIN_ONLY and not self._is_admin(actor):
            return Decision(allowed=False, reason=f"{action.value} requires administrator")

        sensitive = {
            Action.EDIT_MESSAGE,
            Action.DELETE_MESSAGE,
            Action.CLICK_INLINE_BUTTON,
            Action.OPEN_DEEP_LINK,
            Action.CHANGE_AVATAR,
        }
        return Decision(
            allowed=True,
            reason="action policy matched",
            requires_approval=action in sensitive,
        )

    def _is_admin(self, actor: Actor) -> bool:
        return actor.role in {ActorRole.OWNER, ActorRole.ADMIN} or actor.telegram_id in self.policy.admin_telegram_ids

    def _access_rule(self, channel: ChannelAccess) -> tuple[AccessMode, set[int]]:
        match channel:
            case ChannelAccess.DIRECT:
                return self.policy.direct_access, self.policy.allowed_direct_ids
            case ChannelAccess.GROUP:
                return self.policy.group_access, self.policy.allowed_group_ids
            case ChannelAccess.CHANNEL:
                return self.policy.channel_access, self.policy.allowed_channel_ids
