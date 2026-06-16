from __future__ import annotations

import re

from .models import Profile
from .selection import extract_sms_code, normalize_phone

try:
    from aiogram import Dispatcher
    from aiogram.filters import Command
    from aiogram.types import Message
except ImportError:  # pragma: no cover - exercised only before dependencies are installed.
    Dispatcher = None
    Command = None
    Message = None


def _require_aiogram() -> None:
    if Dispatcher is None or Command is None:
        raise RuntimeError("aiogram is not installed. Run: pip install -r requirements.txt")


def _command_args(text: str | None) -> str:
    if not text:
        return ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _parse_time_window(args: str) -> tuple[str, str] | None:
    if not args:
        return None
    match = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", args)
    if not match:
        return None
    return match.group(1), match.group(2)


def _parse_target_dates(args: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", args))


def build_dispatcher(manager, storage):
    _require_aiogram()
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def start(message: Message):
        await message.answer(
            "Бот PADL готов.\n\n"
            "1. Запустить мониторинг: /search 17:00-22:00\n"
            "   Или указать дату: /search 2026-06-12 17:00-22:00\n"
            "2. Бот только уведомляет о свободных слотах.\n"
            "   Записывайтесь вручную на сайте PADL.\n"
            "Другие команды: /now, /status, /stop"
        )

    @dp.message(Command("profile"))
    async def profile(message: Message):
        args = _command_args(message.text).split()
        if len(args) != 4:
            await message.answer("Формат: /profile ИМЯ ФАМИЛИЯ ТЕЛЕФОН ПОЧТА")
            return
        first_name, last_name, raw_phone, email = args
        phone = normalize_phone(raw_phone)
        if phone is None:
            await message.answer(
                "Телефон должен быть российским мобильным номером, например +79161234567."
            )
            return
        if "@" not in email:
            await message.answer("Почта выглядит некорректно.")
            return
        storage.save_profile(
            Profile(
                chat_id=message.chat.id,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                email=email,
            )
        )
        await message.answer(
            "Профиль сохранён. Для мониторинга профиль не нужен. "
            "Запустите мониторинг: /search 17:00-22:00"
        )

    @dp.message(Command("search"))
    async def search(message: Message):
        preferences = storage.get_preferences(message.chat.id)
        args = _command_args(message.text)
        window = _parse_time_window(args)
        target_dates = _parse_target_dates(args)
        if window:
            preferences = type(preferences)(
                start_time=window[0],
                end_time=window[1],
                tickets_count=preferences.tickets_count,
                durations=preferences.durations,
                venue_ids=preferences.venue_ids,
                target_dates=target_dates,
                event_type=preferences.event_type,
                poll_interval_seconds=preferences.poll_interval_seconds,
            )
        try:
            response = await manager.start_search(message.chat.id, preferences)
        except Exception as exc:
            response = str(exc)
        await message.answer(response)

    @dp.message(Command("status"))
    async def status(message: Message):
        await message.answer(await manager.status_message(message.chat.id))

    @dp.message(Command("now"))
    async def now(message: Message):
        try:
            response = await manager.current_slots_message(message.chat.id)
        except Exception as exc:
            response = str(exc)
        await message.answer(response)

    @dp.message(Command("stop"))
    async def stop(message: Message):
        await message.answer(await manager.stop_search(message.chat.id))

    @dp.message(Command("code"))
    async def code(message: Message):
        sms_code = extract_sms_code(_command_args(message.text))
        if not sms_code:
            await message.answer("Формат: /code 1234")
            return
        try:
            await manager.submit_sms_code(message.chat.id, sms_code)
        except Exception as exc:
            await message.answer(str(exc))

    @dp.message(Command("resend"))
    async def resend(message: Message):
        try:
            response = await manager.resend_sms_code(message.chat.id)
        except Exception as exc:
            response = str(exc)
        await message.answer(response)

    return dp
