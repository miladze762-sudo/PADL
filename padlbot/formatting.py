from __future__ import annotations

from .models import BookingResult, PendingBooking, SlotCandidate

TELEGRAM_MESSAGE_LIMIT = 4096


def format_slot(slot: SlotCandidate, tickets_count: int | None = None) -> str:
    tickets = f"\nPlaces: {tickets_count}" if tickets_count is not None else ""
    return (
        f"Venue: {slot.venue_title}\n"
        f"Court: {slot.court_title}\n"
        f"Date: {slot.starts_at:%Y-%m-%d}\n"
        f"Time: {slot.starts_at:%H:%M}-{slot.ends_at:%H:%M}\n"
        f"Duration: {slot.duration_minutes} min"
        f"{tickets}"
    )


def format_monitoring_slots(slots: list[SlotCandidate], tickets_count: int) -> str:
    slot_lines = []
    for index, slot in enumerate(slots, start=1):
        slot_lines.append(f"{index}.\n" + format_slot(slot, tickets_count))
    return (
        "Free PADL slots found. Register manually on the site:\n\n"
        + "\n\n".join(slot_lines)
    )


def format_monitoring_slot_messages(
    slots: list[SlotCandidate],
    tickets_count: int,
    max_message_length: int = TELEGRAM_MESSAGE_LIMIT,
) -> list[str]:
    header = "Free PADL slots found. Register manually on the site:"
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
        "Slot held. Waiting for SMS code. Send /code 1234 when it arrives. "
        "If SMS does not arrive, send /resend.\n\n"
        + format_slot(
            pending.slot,
            pending.tickets_count,
        )
    )


def format_booking_result(result: BookingResult) -> str:
    return (
        "Booking confirmed!\n\n"
        + format_slot(result.slot, result.tickets_count)
        + f"\nBooking id: #{result.booking_id}\n\n"
        + "What date/time should I monitor next? Send /search 2026-06-12 17:00-22:00 "
        + "or /search 17:00-22:00."
    )
