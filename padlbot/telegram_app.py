from __future__ import annotations

from dataclasses import replace

from .localization import start_help_message
from .models import Profile, SearchPreferences
from .selection import extract_sms_code, normalize_phone
from .venues import (
    VenueSelectionError,
    current_venues_message,
    parse_venue_ids,
    venues_saved_message,
)

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


def build_dispatcher(manager, storage):
    _require_aiogram()
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def start(message: Message):
        await message.answer(start_help_message())

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
            "Запустите мониторинг: /search"
        )

    @dp.message(Command("venues"))
    async def venues(message: Message):
        args = _command_args(message.text)
        stored_preferences = storage.get_preferences(message.chat.id)
        if not args:
            await message.answer(current_venues_message(stored_preferences.venue_ids))
            return
        try:
            venue_ids = parse_venue_ids(args)
        except VenueSelectionError as exc:
            await message.answer(str(exc))
            return
        storage.save_preferences(
            message.chat.id,
            replace(stored_preferences, venue_ids=venue_ids),
        )
        await message.answer(venues_saved_message(venue_ids))

    @dp.message(Command("search"))
    async def search(message: Message):
        stored_preferences = storage.get_preferences(message.chat.id)
        preferences = SearchPreferences(
            venue_ids=stored_preferences.venue_ids,
            poll_interval_seconds=stored_preferences.poll_interval_seconds,
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
