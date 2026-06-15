from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional


MOSCOW_TZ = timezone(timedelta(hours=3))
DEFAULT_VENUE_IDS = (12, 14, 15)
DEFAULT_DURATIONS = (120, 90, 60)


def parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MOSCOW_TZ)
    return parsed.astimezone(MOSCOW_TZ)


@dataclass(frozen=True)
class SearchPreferences:
    start_time: str = "17:00"
    end_time: str = "22:00"
    tickets_count: int = 2
    durations: tuple[int, ...] = DEFAULT_DURATIONS
    venue_ids: tuple[int, ...] = DEFAULT_VENUE_IDS
    target_dates: tuple[str, ...] = ()
    event_type: str = "free_play"
    poll_interval_seconds: int = 15


@dataclass(frozen=True)
class SlotCandidate:
    venue_id: int
    venue_title: str
    court_id: int
    court_title: str
    date_key: str
    event_id: int
    starts_at: str | datetime
    ends_at: str | datetime
    duration_minutes: int
    available_tickets: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "starts_at", parse_datetime(self.starts_at))
        object.__setattr__(self, "ends_at", parse_datetime(self.ends_at))


@dataclass(frozen=True)
class Profile:
    chat_id: int
    first_name: str
    last_name: str
    phone: str
    email: str


@dataclass
class PendingBooking:
    session_id: str
    hold_id: str
    slot: SlotCandidate
    tickets_count: int
    expires_at: Optional[str] = None
    result: Optional["BookingResult"] = None


@dataclass(frozen=True)
class BookingResult:
    booking_id: str
    slot: SlotCandidate
    tickets_count: int
