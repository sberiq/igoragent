import bootstrap  # noqa: F401

import asyncio
import logging
import os

from igoragent_core.policy_engine import Action, Actor, ChannelAccess, PolicyEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run() -> None:
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_path = os.getenv("TELEGRAM_SESSION_PATH")
    if not all([api_id, api_hash, session_path]):
        logger.warning("Telegram worker is not configured; refusing to connect")
        return

    from telethon import TelegramClient

    client = TelegramClient(session_path, int(api_id), api_hash)
    engine = PolicyEngine.from_environment() if hasattr(PolicyEngine, "from_environment") else None
    del engine
    await client.start()
    logger.info("Telegram client connected; inbound handlers must be configured through the control plane")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(run())
