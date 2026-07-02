from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable

import aiohttp

from .config import Config
from .outdoor_api import OutdoorApiClient
from .service import SearchManager
from .sms_webhook import start_sms_webhook
from .storage import Storage
from .telegram_polling import TelegramBot, is_telegram_conflict_error, polling_loop


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_heartbeat_payload(
    *,
    status: str,
    generation: str,
    telegram_polling: str,
    active_search_tasks: int,
    last_update_id: int | None = None,
    started_at: str,
    last_loop_error: str | None = None,
    exit_reason: str | None = None,
) -> dict:
    payload = {
        "kind": "padl-bot-daemon",
        "status": status,
        "heartbeatAt": utc_now_iso(),
        "generation": generation,
        "telegramPolling": telegram_polling,
        "activeSearchTasks": active_search_tasks,
        "lastUpdateId": last_update_id,
        "lastLoopError": last_loop_error,
        "startedAt": started_at,
    }
    if exit_reason is not None:
        payload["exitReason"] = exit_reason
    return payload


class HeartbeatReporter:
    def __init__(
        self,
        *,
        run_id: str,
        secret_key: str,
        generation: str,
        max_failures: int,
        request: Callable[[dict], Awaitable[None]] | None = None,
    ):
        self.run_id = run_id
        self.secret_key = secret_key
        self.generation = generation
        self.max_failures = max_failures
        self.failure_count = 0
        self.heartbeat_unhealthy = False
        self._request = request or self._default_request
        self.started_at = utc_now_iso()
        self.last_update_id: int | None = None
        self.telegram_polling = "active"
        self.last_loop_error: str | None = None

    async def update(
        self,
        *,
        status: str,
        active_search_tasks: int,
        telegram_polling: str | None = None,
        last_loop_error: str | None = None,
        exit_reason: str | None = None,
    ) -> None:
        effective_telegram_polling = telegram_polling or self.telegram_polling
        effective_last_loop_error = last_loop_error if last_loop_error is not None else self.last_loop_error
        payload = build_heartbeat_payload(
            status=status,
            generation=self.generation,
            telegram_polling=effective_telegram_polling,
            active_search_tasks=active_search_tasks,
            last_update_id=self.last_update_id,
            started_at=self.started_at,
            last_loop_error=effective_last_loop_error,
            exit_reason=exit_reason,
        )
        try:
            await self._request(payload)
            self.failure_count = 0
            self.heartbeat_unhealthy = False
        except Exception as exc:
            self.failure_count += 1
            if self.max_failures > 0 and self.failure_count >= self.max_failures:
                self.heartbeat_unhealthy = True
                print(
                    "Trigger metadata heartbeat failed "
                    f"{self.failure_count} consecutive times; polling continues: {exc}"
                )
            else:
                print(f"Trigger metadata heartbeat failed: {exc}")

    async def _default_request(self, payload: dict) -> None:
        url = f"https://api.trigger.dev/api/v1/runs/{self.run_id}/metadata"
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=headers, json={"metadata": payload}) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise RuntimeError(f"metadata update failed: {response.status} {text}")


async def main() -> int:
    config = Config.from_env()
    if config.runtime_mode != "trigger-daemon":
        raise RuntimeError("padlbot.trigger_daemon requires PADL_RUNTIME_MODE=trigger-daemon")
    return await run_daemon(config)


async def run_daemon(config: Config) -> int:
    storage = Storage(config.db_path)
    storage.initialize()
    reporter = HeartbeatReporter(
        run_id=require_env("TRIGGER_RUN_ID"),
        secret_key=config.trigger_secret_key,
        generation=require_env("PADL_DAEMON_GENERATION", "unknown"),
        max_failures=config.heartbeat_max_failures,
    )

    async with OutdoorApiClient(
        config.site_base_url,
        timeout_seconds=config.request_timeout_seconds,
    ) as api:
        async with TelegramBot(config.telegram_bot_token) as bot:
            if config.delete_webhook_on_start:
                await bot.delete_webhook(
                    drop_pending_updates=config.drop_pending_updates_on_start,
                )

            manager = SearchManager(api=api, storage=storage, bot=bot, config=config)
            resumed_chat_ids = set(
                manager.resume_active_searches(storage.list_active_search_chat_ids())
            )
            if config.auto_start_search and config.admin_chat_id is not None and config.admin_chat_id not in resumed_chat_ids:
                preferences = storage.get_preferences(config.admin_chat_id)
                if config.default_venue_ids:
                    from dataclasses import replace

                    preferences = replace(preferences, venue_ids=config.default_venue_ids)
                    storage.save_preferences(config.admin_chat_id, preferences)
                response = await manager.start_search(config.admin_chat_id, preferences)
                await bot.send_message(config.admin_chat_id, response)

            heartbeat_task = asyncio.create_task(heartbeat_loop(reporter, manager, config))
            rotation_task = asyncio.create_task(asyncio.sleep(config.daemon_rotate_after_seconds))
            polling_task = asyncio.create_task(
                polling_loop(
                    bot=bot,
                    manager=manager,
                    storage=storage,
                    on_update_processed=lambda update_id: setattr(reporter, "last_update_id", update_id),
                    on_polling_error=lambda status, error: remember_polling_error(reporter, status, error),
                    conflict_exit_seconds=config.telegram_conflict_exit_seconds,
                )
            )
            done, pending = await asyncio.wait(
                {polling_task, rotation_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            polling_error = polling_task.exception() if polling_task in done else None
            if polling_error is not None:
                reporter.telegram_polling = "conflict" if is_telegram_conflict_error(polling_error) else "error"
                reporter.last_loop_error = str(polling_error)
            if rotation_task in done:
                await reporter.update(
                    status="rotating",
                    active_search_tasks=count_active_tasks(manager),
                    telegram_polling="stopping",
                )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            await manager.cancel_all_searches()
            await reporter.update(
                status="exiting",
                active_search_tasks=count_active_tasks(manager),
                telegram_polling=reporter.telegram_polling if polling_error is not None else "stopped",
                last_loop_error=reporter.last_loop_error,
                exit_reason=exit_reason_for(polling_error, rotation_task in done),
            )
            if polling_error is not None:
                raise polling_error
    return 0


async def heartbeat_loop(reporter: HeartbeatReporter, manager: SearchManager, config: Config) -> None:
    while True:
        await reporter.update(
            status="running",
            active_search_tasks=count_active_tasks(manager),
            telegram_polling="active",
        )
        await asyncio.sleep(config.heartbeat_seconds)


def count_active_tasks(manager: SearchManager) -> int:
    return sum(1 for task in manager.state.tasks.values() if not task.done())


def remember_polling_error(reporter: HeartbeatReporter, status: str, error: str) -> None:
    reporter.telegram_polling = status
    reporter.last_loop_error = error


def exit_reason_for(polling_error: BaseException | None, rotation_done: bool) -> str:
    if polling_error is not None:
        return "telegram-conflict" if is_telegram_conflict_error(polling_error) else "polling-error"
    return "planned-rotation" if rotation_done else "polling-exit"


def require_env(name: str, default: str | None = None) -> str:
    import os

    value = os.environ.get(name, default)
    if value is None or value == "":
        raise RuntimeError(f"{name} is required")
    return value
