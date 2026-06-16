from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from .booking import BookingCoordinator
from .config import Config
from .formatting import format_booking_result, format_monitoring_slot_messages
from .models import MOSCOW_TZ, PendingBooking, SearchPreferences, SlotCandidate, parse_datetime
from .scanner import SlotScanner
from .storage import Storage


class UserVisibleError(RuntimeError):
    pass


SMS_STATUS_POLL_SECONDS = 10
SMS_AUTO_RESEND_LIMIT = 0
SMS_FAILED_SLOT_COOLDOWN_SECONDS = 600
SMS_FAILED_PHONE_COOLDOWN_SECONDS = 180


@dataclass
class RuntimeState:
    pending: dict[int, PendingBooking]
    tasks: dict[int, asyncio.Task]
    blocked_slots: dict[int, dict[tuple, datetime]]
    sms_paused_until: dict[int, datetime]
    notified_slots: dict[int, set[tuple]]

    @classmethod
    def empty(cls) -> "RuntimeState":
        return cls(
            pending={},
            tasks={},
            blocked_slots={},
            sms_paused_until={},
            notified_slots={},
        )


class SearchManager:
    def __init__(self, *, api, storage: Storage, bot, config: Config):
        self.api = api
        self.storage = storage
        self.bot = bot
        self.config = config
        self.scanner = SlotScanner(api)
        self.coordinator = BookingCoordinator(api)
        self.state = RuntimeState.empty()

    async def start_search(self, chat_id: int, preferences: SearchPreferences) -> str:
        existing = self.state.tasks.get(chat_id)
        if existing and not existing.done():
            return "Monitoring is already active."
        self.storage.save_preferences(chat_id, preferences)
        self.storage.set_search_active(chat_id, True, "monitoring")
        self.state.notified_slots[chat_id] = set()
        self.state.tasks[chat_id] = asyncio.create_task(self._search_loop(chat_id))
        return (
            "Monitoring started: free play, all venues, "
            f"{preferences.start_time}-{preferences.end_time}, "
            f"{preferences.tickets_count} places"
            + (
                f", dates: {', '.join(preferences.target_dates)}."
                if preferences.target_dates
                else "."
            )
        )

    async def stop_search(self, chat_id: int) -> str:
        task = self.state.tasks.get(chat_id)
        if task and not task.done():
            task.cancel()
        self.state.pending.pop(chat_id, None)
        self.state.blocked_slots.pop(chat_id, None)
        self.state.sms_paused_until.pop(chat_id, None)
        self.state.notified_slots.pop(chat_id, None)
        self.storage.set_search_active(chat_id, False, "stopped")
        return "Monitoring stopped."

    async def status_message(self, chat_id: int) -> str:
        active, status = self.storage.get_search_state(chat_id)
        last = self.storage.get_last_booking(chat_id)
        parts = [f"Monitoring: {'active' if active else 'inactive'}"]
        if status:
            parts.append(f"Status: {status}")
        if chat_id in self.state.pending:
            parts.append("Pending booking: waiting for SMS code")
        if last:
            parts.append("Last booking:\n" + format_booking_result(last))
        return "\n\n".join(parts)

    async def submit_sms_code(self, chat_id: int, code: str) -> str:
        pending = self.state.pending.get(chat_id)
        if pending is None:
            raise UserVisibleError("No active held slot is waiting for an SMS code.")
        profile = self.storage.get_profile(chat_id)
        if profile is None:
            raise UserVisibleError("Profile is missing.")
        result = await self.coordinator.confirm_with_sms(pending, profile, code)
        self.storage.save_last_booking(chat_id, result)
        self.storage.set_search_active(chat_id, False, "confirmed")
        self.state.pending.pop(chat_id, None)
        message = format_booking_result(result)
        await self.bot.send_message(chat_id, message)
        return message

    async def resend_sms_code(self, chat_id: int) -> str:
        pending = self.state.pending.get(chat_id)
        if pending is None:
            raise UserVisibleError("No active held slot is waiting for an SMS code.")
        profile = self.storage.get_profile(chat_id)
        if profile is None:
            raise UserVisibleError("Profile is missing.")
        await self.coordinator.resend_sms(pending, profile)
        return "SMS requested again. When it arrives, send /code 1234."

    async def _search_loop(self, chat_id: int) -> None:
        while True:
            preferences = self.storage.get_preferences(chat_id)
            try:
                slots = await self.scanner.find_slots(preferences)
                new_slots = self._new_slots_for_notification(chat_id, slots)
                if new_slots:
                    for message in format_monitoring_slot_messages(
                        new_slots,
                        preferences.tickets_count,
                    ):
                        await self.bot.send_message(chat_id, message)
                    self.storage.set_search_active(
                        chat_id,
                        True,
                        f"monitoring, {len(new_slots)} new slot(s) found",
                    )
                else:
                    status = "monitoring, no matching slot yet" if not slots else "monitoring, no new slots"
                    self.storage.set_search_active(chat_id, True, status)
                await asyncio.sleep(preferences.poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.storage.set_search_active(chat_id, True, f"temporary error: {exc}")
                await asyncio.sleep(preferences.poll_interval_seconds)

    def _new_slots_for_notification(
        self,
        chat_id: int,
        slots: list[SlotCandidate],
    ) -> list[SlotCandidate]:
        notified = self.state.notified_slots.setdefault(chat_id, set())
        new_slots: list[SlotCandidate] = []
        for slot in slots:
            key = self._slot_key(slot)
            if key in notified:
                continue
            notified.add(key)
            new_slots.append(slot)
        return new_slots

    async def _monitor_pending_sms(self, chat_id: int, pending: PendingBooking) -> bool:
        resends = 0
        while True:
            await asyncio.sleep(SMS_STATUS_POLL_SECONDS)
            if self.state.pending.get(chat_id) is not pending:
                return False

            profile = self.storage.get_profile(chat_id)
            if profile is None:
                self.state.pending.pop(chat_id, None)
                self.storage.set_search_active(chat_id, False, "profile missing")
                await self.bot.send_message(chat_id, "Profile is missing.")
                return False

            try:
                status = await self.coordinator.sms_status(pending, profile)
            except Exception:
                status = {}

            if self._pending_expired(pending, status):
                self.state.pending.pop(chat_id, None)
                self._block_slot(chat_id, pending.slot)
                self._pause_sms_attempts(chat_id)
                self.storage.set_search_active(chat_id, True, "SMS hold expired, searching again")
                await self.bot.send_message(
                    chat_id,
                    "SMS window expired before confirmation. I am skipping this slot "
                    "temporarily and searching again.",
                )
                return True

            status_name = str(status.get("status") or "").lower()
            retry_after = self._retry_after_seconds(status)
            if status_name == "failed":
                if resends < SMS_AUTO_RESEND_LIMIT and retry_after <= 0:
                    try:
                        await self.coordinator.resend_sms(pending, profile)
                    except Exception:
                        self.state.pending.pop(chat_id, None)
                        self._block_slot(chat_id, pending.slot)
                        self._pause_sms_attempts(chat_id)
                        self.storage.set_search_active(
                            chat_id,
                            True,
                            "SMS resend failed, searching again",
                        )
                        await self.bot.send_message(
                            chat_id,
                            "SMS resend failed. I am searching again.",
                        )
                        return True
                    resends += 1
                    await self.bot.send_message(
                        chat_id,
                        "SMS did not deliver, so I requested it one more time.",
                    )
                    continue

                self.state.pending.pop(chat_id, None)
                self._block_slot(chat_id, pending.slot)
                self._pause_sms_attempts(chat_id)
                self.storage.set_search_active(chat_id, True, "SMS failed, searching again")
                await self.bot.send_message(
                    chat_id,
                    "SMS did not deliver. I am skipping this slot temporarily and searching again.",
                )
                return True

    def _pending_expired(self, pending: PendingBooking, status: dict | None = None) -> bool:
        expires_at = (status or {}).get("expires_at") or pending.expires_at
        if not expires_at:
            return False
        return parse_datetime(str(expires_at)) <= datetime.now(MOSCOW_TZ)

    def _retry_after_seconds(self, status: dict) -> int:
        try:
            return int(status.get("retry_after_seconds") or 0)
        except (TypeError, ValueError):
            return 0

    def _first_unblocked_slot(
        self,
        chat_id: int,
        slots: list[SlotCandidate],
    ) -> SlotCandidate | None:
        for slot in slots:
            if not self._is_slot_blocked(chat_id, slot):
                return slot
        return None

    def _slot_key(self, slot: SlotCandidate) -> tuple:
        return (
            slot.venue_id,
            slot.court_id,
            slot.event_id,
            slot.starts_at.isoformat(),
            slot.ends_at.isoformat(),
            slot.duration_minutes,
        )

    def _block_slot(
        self,
        chat_id: int,
        slot: SlotCandidate,
        seconds: int = SMS_FAILED_SLOT_COOLDOWN_SECONDS,
    ) -> None:
        expires_at = datetime.now(MOSCOW_TZ) + timedelta(seconds=seconds)
        blocked = self.state.blocked_slots.setdefault(chat_id, {})
        blocked[self._slot_key(slot)] = expires_at

    def _is_slot_blocked(self, chat_id: int, slot: SlotCandidate) -> bool:
        blocked = self.state.blocked_slots.setdefault(chat_id, {})
        key = self._slot_key(slot)
        expires_at = blocked.get(key)
        if expires_at is None:
            return False
        if expires_at <= datetime.now(MOSCOW_TZ):
            blocked.pop(key, None)
            return False
        return True

    def _pause_sms_attempts(
        self,
        chat_id: int,
        seconds: int = SMS_FAILED_PHONE_COOLDOWN_SECONDS,
    ) -> None:
        self.state.sms_paused_until[chat_id] = datetime.now(MOSCOW_TZ) + timedelta(
            seconds=seconds
        )

    def _is_sms_paused(self, chat_id: int) -> bool:
        expires_at = self.state.sms_paused_until.get(chat_id)
        if expires_at is None:
            return False
        if expires_at <= datetime.now(MOSCOW_TZ):
            self.state.sms_paused_until.pop(chat_id, None)
            return False
        return True
