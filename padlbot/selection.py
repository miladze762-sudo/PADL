from __future__ import annotations

import re
from datetime import time
from typing import Iterable, Optional

from .models import MOSCOW_TZ, SearchPreferences, SlotCandidate, parse_datetime


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute), tzinfo=MOSCOW_TZ)


def _inside_window(slot: SlotCandidate, preferences: SearchPreferences) -> bool:
    start = slot.starts_at.astimezone(MOSCOW_TZ).timetz().replace(second=0, microsecond=0)
    end = slot.ends_at.astimezone(MOSCOW_TZ).timetz().replace(second=0, microsecond=0)
    return _parse_hhmm(preferences.start_time) <= start and end <= _parse_hhmm(preferences.end_time)


def extract_candidates(
    *,
    availability: dict,
    venue_id: int,
    venue_title: str,
    court_id: int,
    court_title: str,
    date_key: str,
    preferences: SearchPreferences,
) -> list[SlotCandidate]:
    if preferences.target_dates and date_key not in preferences.target_dates:
        return []

    candidates: list[SlotCandidate] = []
    allowed_durations = set(preferences.durations)

    for event in availability.get("events", []):
        event_id = int(event.get("id") or event.get("event_id"))
        for start in event.get("starts", []):
            for duration_text, duration_data in (start.get("durations") or {}).items():
                try:
                    duration = int(duration_text)
                except (TypeError, ValueError):
                    continue
                if duration not in allowed_durations:
                    continue
                if not duration_data.get("enabled") or not duration_data.get("booking_open"):
                    continue
                available_tickets = int(duration_data.get("available_tickets") or 0)
                if available_tickets < preferences.tickets_count:
                    continue

                slot = SlotCandidate(
                    venue_id=venue_id,
                    venue_title=venue_title,
                    court_id=court_id,
                    court_title=court_title,
                    date_key=date_key,
                    event_id=event_id,
                    starts_at=duration_data.get("starts_at") or start.get("starts_at"),
                    ends_at=duration_data.get("ends_at"),
                    duration_minutes=duration,
                    available_tickets=available_tickets,
                )
                if _inside_window(slot, preferences):
                    candidates.append(slot)

    return candidates


def extract_candidates_from_available_events(
    *,
    available_events: Iterable[dict],
    venue_id: int,
    venue_title: str,
    court_id: int,
    court_title: str,
    preferences: SearchPreferences,
) -> list[SlotCandidate]:
    candidates: list[SlotCandidate] = []
    allowed_durations = set(preferences.durations)

    for event in available_events:
        try:
            event_id = int(event.get("id") or event.get("event_id"))
        except (TypeError, ValueError):
            continue
        for available_slot in event.get("available_slots") or []:
            try:
                duration = int(available_slot.get("duration_minutes") or 0)
                available_tickets = int(available_slot.get("available_tickets") or 0)
            except (TypeError, ValueError):
                continue
            if duration not in allowed_durations:
                continue
            if available_tickets < preferences.tickets_count:
                continue

            starts_at = available_slot.get("starts_at")
            ends_at = available_slot.get("ends_at")
            if not starts_at or not ends_at:
                continue

            date_key = parse_datetime(str(starts_at)).date().isoformat()
            if preferences.target_dates and date_key not in preferences.target_dates:
                continue

            slot = SlotCandidate(
                venue_id=venue_id,
                venue_title=venue_title,
                court_id=court_id,
                court_title=court_title,
                date_key=date_key,
                event_id=event_id,
                starts_at=str(starts_at),
                ends_at=str(ends_at),
                duration_minutes=duration,
                available_tickets=available_tickets,
            )
            if _inside_window(slot, preferences):
                candidates.append(slot)

    return candidates


def choose_best_slot(
    candidates: Iterable[SlotCandidate],
    preferences: SearchPreferences,
) -> Optional[SlotCandidate]:
    ordered = sort_slots(candidates, preferences)
    return ordered[0] if ordered else None


def sort_slots(
    candidates: Iterable[SlotCandidate],
    preferences: SearchPreferences,
) -> list[SlotCandidate]:
    venue_order = {venue_id: index for index, venue_id in enumerate(preferences.venue_ids)}
    return sorted(
        candidates,
        key=lambda slot: (
            slot.starts_at,
            venue_order.get(slot.venue_id, len(venue_order)),
            -slot.duration_minutes,
            slot.court_id,
            slot.event_id,
        ),
    )


def extract_sms_code(text: str) -> Optional[str]:
    match = re.search(r"(?<!\d)(\d{4})(?!\d)", text)
    return match.group(1) if match else None


def normalize_phone(phone: str) -> Optional[str]:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        digits = "7" + digits
    elif len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) != 11 or not digits.startswith("7"):
        return None
    return "+" + digits


def format_phone_for_site(phone: str) -> str:
    normalized = normalize_phone(phone)
    if normalized is None:
        return phone
    return normalized
