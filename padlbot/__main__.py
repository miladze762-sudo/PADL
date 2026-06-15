from __future__ import annotations

import asyncio

from .config import Config
from .outdoor_api import OutdoorApiClient
from .service import SearchManager
from .single_instance import SingleInstanceError, acquire_single_instance_lock
from .sms_webhook import start_sms_webhook
from .storage import Storage
from .telegram_polling import TelegramBot, polling_loop


async def main(config: Config) -> None:
    storage = Storage(config.db_path)
    storage.initialize()

    async with OutdoorApiClient(
        config.site_base_url,
        timeout_seconds=config.request_timeout_seconds,
    ) as api:
        async with TelegramBot(config.telegram_bot_token) as bot:
            manager = SearchManager(api=api, storage=storage, bot=bot, config=config)
            webhook_runner = await start_sms_webhook(manager, config)
            if config.auto_start_search and config.admin_chat_id is not None:
                preferences = storage.get_preferences(config.admin_chat_id)
                response = await manager.start_search(config.admin_chat_id, preferences)
                await bot.send_message(config.admin_chat_id, response)
            try:
                await polling_loop(bot=bot, manager=manager, storage=storage)
            finally:
                await webhook_runner.cleanup()


if __name__ == "__main__":
    app_config = Config.from_env()
    try:
        lock = acquire_single_instance_lock(app_config.lock_host, app_config.lock_port)
    except SingleInstanceError as exc:
        print(str(exc))
    else:
        try:
            asyncio.run(main(app_config))
        finally:
            lock.close()
