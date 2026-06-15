from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from .models import BookingResult, Profile, SearchPreferences, SlotCandidate


class Storage:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    chat_id INTEGER PRIMARY KEY,
                    first_name TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    email TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    chat_id INTEGER PRIMARY KEY,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    tickets_count INTEGER NOT NULL,
                    durations TEXT NOT NULL,
                    venue_ids TEXT NOT NULL,
                    target_dates TEXT NOT NULL DEFAULT '[]',
                    event_type TEXT NOT NULL,
                    poll_interval_seconds INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS search_state (
                    chat_id INTEGER PRIMARY KEY,
                    active INTEGER NOT NULL DEFAULT 0,
                    last_status TEXT
                );

                CREATE TABLE IF NOT EXISTS last_bookings (
                    chat_id INTEGER PRIMARY KEY,
                    booking_id TEXT NOT NULL,
                    slot_json TEXT NOT NULL,
                    tickets_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._ensure_column(conn, "preferences", "target_dates", "TEXT NOT NULL DEFAULT '[]'")

    def save_profile(self, profile: Profile) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO profiles (chat_id, first_name, last_name, phone, email)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    phone = excluded.phone,
                    email = excluded.email
                """,
                (
                    profile.chat_id,
                    profile.first_name,
                    profile.last_name,
                    profile.phone,
                    profile.email,
                ),
            )

    def get_profile(self, chat_id: int) -> Optional[Profile]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT chat_id, first_name, last_name, phone, email FROM profiles WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if row is None:
            return None
        return Profile(
            chat_id=int(row["chat_id"]),
            first_name=str(row["first_name"]),
            last_name=str(row["last_name"]),
            phone=str(row["phone"]),
            email=str(row["email"]),
        )

    def save_preferences(self, chat_id: int, preferences: SearchPreferences) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preferences (
                    chat_id, start_time, end_time, tickets_count, durations,
                    venue_ids, target_dates, event_type, poll_interval_seconds
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    start_time = excluded.start_time,
                    end_time = excluded.end_time,
                    tickets_count = excluded.tickets_count,
                    durations = excluded.durations,
                    venue_ids = excluded.venue_ids,
                    target_dates = excluded.target_dates,
                    event_type = excluded.event_type,
                    poll_interval_seconds = excluded.poll_interval_seconds
                """,
                (
                    chat_id,
                    preferences.start_time,
                    preferences.end_time,
                    preferences.tickets_count,
                    json.dumps(list(preferences.durations)),
                    json.dumps(list(preferences.venue_ids)),
                    json.dumps(list(preferences.target_dates)),
                    preferences.event_type,
                    preferences.poll_interval_seconds,
                ),
            )

    def get_preferences(self, chat_id: int) -> SearchPreferences:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT start_time, end_time, tickets_count, durations, venue_ids,
                       target_dates, event_type, poll_interval_seconds
                FROM preferences
                WHERE chat_id = ?
                """,
                (chat_id,),
            ).fetchone()
        if row is None:
            return SearchPreferences()
        return SearchPreferences(
            start_time=str(row["start_time"]),
            end_time=str(row["end_time"]),
            tickets_count=int(row["tickets_count"]),
            durations=tuple(int(item) for item in json.loads(row["durations"])),
            venue_ids=tuple(int(item) for item in json.loads(row["venue_ids"])),
            target_dates=tuple(str(item) for item in json.loads(row["target_dates"])),
            event_type=str(row["event_type"]),
            poll_interval_seconds=int(row["poll_interval_seconds"]),
        )

    def set_search_active(self, chat_id: int, active: bool, status: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO search_state (chat_id, active, last_status)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    active = excluded.active,
                    last_status = excluded.last_status
                """,
                (chat_id, 1 if active else 0, status),
            )

    def get_search_state(self, chat_id: int) -> tuple[bool, str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT active, last_status FROM search_state WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if row is None:
            return False, ""
        return bool(row["active"]), str(row["last_status"] or "")

    def save_last_booking(self, chat_id: int, result: BookingResult) -> None:
        slot = result.slot
        slot_json = json.dumps(
            {
                "venue_id": slot.venue_id,
                "venue_title": slot.venue_title,
                "court_id": slot.court_id,
                "court_title": slot.court_title,
                "date_key": slot.date_key,
                "event_id": slot.event_id,
                "starts_at": slot.starts_at.isoformat(),
                "ends_at": slot.ends_at.isoformat(),
                "duration_minutes": slot.duration_minutes,
                "available_tickets": slot.available_tickets,
            }
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO last_bookings (chat_id, booking_id, slot_json, tickets_count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    booking_id = excluded.booking_id,
                    slot_json = excluded.slot_json,
                    tickets_count = excluded.tickets_count,
                    created_at = CURRENT_TIMESTAMP
                """,
                (chat_id, result.booking_id, slot_json, result.tickets_count),
            )

    def get_last_booking(self, chat_id: int) -> Optional[BookingResult]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT booking_id, slot_json, tickets_count FROM last_bookings WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if row is None:
            return None
        slot_data = json.loads(row["slot_json"])
        return BookingResult(
            booking_id=str(row["booking_id"]),
            slot=SlotCandidate(**slot_data),
            tickets_count=int(row["tickets_count"]),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
