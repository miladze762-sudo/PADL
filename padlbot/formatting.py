from __future__ import annotations

from .localization import PADL_BOOKING_URL, localize_court_title, localize_venue_title
from .models import BookingResult, PendingBooking, SlotCandidate

TELEGRAM_MESSAGE_LIMIT = 4096


def format_slot(slot: SlotCandidate, tickets_count: int | None = None) -> str:
    tickets = f"\nМест: {tickets_count}" if tickets_count is not None else ""
    return (
        f"Площадка: {localize_venue_title(slot.venue_title)}\n"
        f"Корт: {localize_court_title(slot.court_title)}\n"
        f"Дата: {slot.starts_at:%Y-%m-%d}\n"
        f"Время: {slot.starts_at:%H:%M}-{slot.ends_at:%H:%M}\n"
        f"Длительность: {slot.duration_minutes} мин"
        f"{tickets}"
    )


def format_monitoring_slots(slots: list[SlotCandidate], tickets_count: int) -> str:
    slot_lines = []
    for index, slot in enumerate(slots, start=1):
        slot_lines.append(f"{index}.\n" + format_slot(slot, tickets_count))
    return (
        f"Найдены свободные слоты PADL. Запишитесь вручную на сайте PADL:\n"
        f"{PADL_BOOKING_URL}\n\n"
        + "\n\n".join(slot_lines)
    )


def format_monitoring_slot_messages(
    slots: list[SlotCandidate],
    tickets_count: int,
    max_message_length: int = TELEGRAM_MESSAGE_LIMIT,
    header: str = (
        "Найдены свободные слоты PADL. Запишитесь вручную на сайте PADL:\n"
        f"{PADL_BOOKING_URL}"
    ),
) -> list[str]:
    messages: list[str] = []
    current = header

    for index, slot in enumerate(slots, start=1):
        entry = f"{index}.\n" + format_slot(slot, tickets_count)
        candidate = current + "\n\n" + entry
        if len(candidate) <= max_message_length or current == header:
            current = candidate
            continue

        messages.append(current)
        current = header + "\n\n" + entry

    messages.append(current)
    return messages


def format_pending(pending: PendingBooking) -> str:
    return (
        "Слот удержан. Жду СМС-код. Когда он придёт, отправьте /code 1234. "
        "Если СМС не пришла, отправьте /resend.\n\n"
        + format_slot(
            pending.slot,
            pending.tickets_count,
        )
    )


def format_booking_result(result: BookingResult) -> str:
    return (
        "Бронь подтверждена!\n\n"
        + format_slot(result.slot, result.tickets_count)
        + f"\nНомер брони: #{result.booking_id}\n\n"
        + "Чтобы снова запустить постоянный мониторинг без ограничения по времени, отправьте /search."
    )
