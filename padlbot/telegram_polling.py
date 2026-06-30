from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any

import aiohttp

from .localization import start_help_message
from .models import Profile, SearchPreferences
from .selection import extract_sms_code, normalize_phone
from .venues import (
    VenueSelectionError,
    current_venues_message,
    parse_venue_ids,
    venues_saved_message,
)


def _command_args(text: str | None) -> str:
    if not text:
        return ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


@dataclass(frozen=True)
class IncomingMessage:
    chat_id: int
    text: str


class TelegramBot:
    def __init__(self, token: str, timeout_seconds: float = 45.0):
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "TelegramBot":
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def send_message(self, chat_id: int, text: str) -> None:
        await self._request(
            "sendMessage",
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )

    async def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": 30, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        data = await self._request("getUpdates", payload)
        return list(data.get("result") or [])

    async def _request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("TelegramBot must be used as an async context manager")
        async with self.session.post(f"{self.base_url}/{method}", json=payload) as response:
            data = await response.json(content_type=None)
            if response.status >= 400 or not data.get("ok", False):
                raise RuntimeError(f"Telegram API error: {data}")
            return data


def _extract_message(update: dict[str, Any]) -> IncomingMessage | None:
    message = update.get("message") or {}
    text = message.get("text")
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not text or chat_id is None:
        return None
    return IncomingMessage(chat_id=int(chat_id), text=str(text))


async def handle_message(message: IncomingMessage, *, bot: TelegramBot, manager, storage) -> None:
    text = message.text.strip()
    command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()

    if command == "/start":
        await bot.send_message(
            message.chat_id,
            start_help_message(),
        )
        return

    if command == "/profile":
        args = _command_args(text).split()
        if len(args) != 4:
            await bot.send_message(message.chat_id, "Формат: /profile ИМЯ ФАМИЛИЯ ТЕЛЕФОН ПОЧТА")
            return
        first_name, last_name, raw_phone, email = args
        phone = normalize_phone(raw_phone)
        if phone is None:
            await bot.send_message(
                message.chat_id,
                "Телефон должен быть российским мобильным номером, например +79161234567.",
            )
            return
        if "@" not in email:
            await bot.send_message(message.chat_id, "Почта выглядит некорректно.")
            return
        storage.save_profile(
            Profile(
                chat_id=message.chat_id,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                email=email,
            )
        )
        await bot.send_message(
            message.chat_id,
            "Профиль сохранён. Для мониторинга профиль не нужен. "
            "Запустите мониторинг: /search",
        )
        return

    if command == "/venues":
        args = _command_args(text)
        stored_preferences = storage.get_preferences(message.chat_id)
        if not args:
            await bot.send_message(
                message.chat_id,
                current_venues_message(stored_preferences.venue_ids),
            )
            return
        try:
            venue_ids = parse_venue_ids(args)
        except VenueSelectionError as exc:
            await bot.send_message(message.chat_id, str(exc))
            return
        storage.save_preferences(
            message.chat_id,
            replace(stored_preferences, venue_ids=venue_ids),
        )
        await bot.send_message(message.chat_id, venues_saved_message(venue_ids))
        return

    if command == "/search":
        stored_preferences = storage.get_preferences(message.chat_id)
        preferences = SearchPreferences(
            venue_ids=stored_preferences.venue_ids,
            poll_interval_seconds=stored_preferences.poll_interval_seconds,
        )
        try:
            response = await manager.start_search(message.chat_id, preferences)
        except Exception as exc:
            response = str(exc)
        await bot.send_message(message.chat_id, response)
        return

    if command == "/now":
        try:
            response = await manager.current_slots_message(message.chat_id)
        except Exception as exc:
            response = str(exc)
        await bot.send_message(message.chat_id, response)
        return

    if command == "/status":
        await bot.send_message(message.chat_id, await manager.status_message(message.chat_id))
        return

    if command == "/stop":
        await bot.send_message(message.chat_id, await manager.stop_search(message.chat_id))
        return

    if command == "/code":
        sms_code = extract_sms_code(_command_args(text))
        if not sms_code:
            await bot.send_message(message.chat_id, "Формат: /code 1234")
            return
        try:
            await manager.submit_sms_code(message.chat_id, sms_code)
        except Exception as exc:
            await bot.send_message(message.chat_id, str(exc))
        return

    if command == "/resend":
        try:
            response = await manager.resend_sms_code(message.chat_id)
        except Exception as exc:
            response = str(exc)
        await bot.send_message(message.chat_id, response)
        return

    await bot.send_message(message.chat_id, "Неизвестная команда. Отправьте /start для справки.")


async def polling_loop(*, bot: TelegramBot, manager, storage) -> None:
    offset: int | None = None
    while True:
        try:
            updates = await bot.get_updates(offset)
            for update in updates:
                offset = int(update["update_id"]) + 1
                message = _extract_message(update)
                if message is not None:
                    await handle_message(message, bot=bot, manager=manager, storage=storage)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Telegram polling error: {exc}")
            await asyncio.sleep(5)
