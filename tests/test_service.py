import unittest
import asyncio
from datetime import datetime, timedelta

from padlbot.models import MOSCOW_TZ, SearchPreferences, SlotCandidate
from padlbot.service import SearchManager


class FakeMonitoringStorage:
    def __init__(self, preferences):
        self.preferences = preferences
        self.saved_preferences = []
        self.statuses = []

    def get_profile(self, chat_id):
        return None

    def save_preferences(self, chat_id, preferences):
        self.preferences = preferences
        self.saved_preferences.append((chat_id, preferences))

    def get_preferences(self, chat_id):
        return self.preferences

    def set_search_active(self, chat_id, active, status=""):
        self.statuses.append((chat_id, active, status))

    def get_search_state(self, chat_id):
        if not self.statuses:
            return False, ""
        _, active, status = self.statuses[-1]
        return active, status

    def get_last_booking(self, chat_id):
        return None


class FakeMonitoringBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text):
        self.messages.append({"chat_id": chat_id, "text": text})


class FakeMonitoringScanner:
    def __init__(self, slots_by_call):
        self.slots_by_call = list(slots_by_call)
        self.calls = 0

    async def find_slots(self, preferences):
        index = min(self.calls, len(self.slots_by_call) - 1)
        self.calls += 1
        return list(self.slots_by_call[index])


class FakeMonitoringCoordinator:
    def __init__(self):
        self.reserve_calls = []

    async def reserve_slot(self, slot, profile, preferences):
        self.reserve_calls.append((slot, profile, preferences))
        raise AssertionError("monitoring must not reserve slots")


async def wait_until(predicate, timeout=1.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


class SearchManagerSlotBlockTests(unittest.TestCase):
    def setUp(self):
        self.manager = SearchManager(api=None, storage=None, bot=None, config=None)
        self.slot = SlotCandidate(
            venue_id=14,
            venue_title="Tretyakovskaya",
            court_id=13,
            court_title="Court 2",
            date_key="2026-06-11",
            event_id=793,
            starts_at="2026-06-11T17:00:00.000+03:00",
            ends_at="2026-06-11T18:00:00.000+03:00",
            duration_minutes=60,
            available_tickets=2,
        )

    def test_blocks_same_slot_temporarily_after_sms_failure(self):
        self.manager._block_slot(100, self.slot, seconds=60)

        self.assertTrue(self.manager._is_slot_blocked(100, self.slot))

    def test_expired_slot_block_is_removed(self):
        self.manager._block_slot(100, self.slot, seconds=60)
        key = self.manager._slot_key(self.slot)
        self.manager.state.blocked_slots[100][key] = datetime.now(MOSCOW_TZ) - timedelta(
            seconds=1
        )

        self.assertFalse(self.manager._is_slot_blocked(100, self.slot))
        self.assertNotIn(key, self.manager.state.blocked_slots[100])

    def test_sms_pause_prevents_immediate_new_sms_attempts(self):
        self.manager._pause_sms_attempts(100, seconds=60)

        self.assertTrue(self.manager._is_sms_paused(100))

    def test_expired_sms_pause_is_removed(self):
        self.manager._pause_sms_attempts(100, seconds=60)
        self.manager.state.sms_paused_until[100] = datetime.now(MOSCOW_TZ) - timedelta(
            seconds=1
        )

        self.assertFalse(self.manager._is_sms_paused(100))
        self.assertNotIn(100, self.manager.state.sms_paused_until)


class SearchManagerMonitoringTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.chat_id = 100
        self.preferences = SearchPreferences(poll_interval_seconds=0.01)
        self.slot = SlotCandidate(
            venue_id=14,
            venue_title="Tretyakovskaya",
            court_id=13,
            court_title="Court 2",
            date_key="2026-06-11",
            event_id=793,
            starts_at="2026-06-11T17:00:00.000+03:00",
            ends_at="2026-06-11T18:00:00.000+03:00",
            duration_minutes=60,
            available_tickets=2,
        )

    def build_manager(self, slots_by_call):
        storage = FakeMonitoringStorage(self.preferences)
        bot = FakeMonitoringBot()
        coordinator = FakeMonitoringCoordinator()
        manager = SearchManager(api=None, storage=storage, bot=bot, config=None)
        manager.scanner = FakeMonitoringScanner(slots_by_call)
        manager.coordinator = coordinator
        return manager, storage, bot, coordinator

    async def test_search_starts_monitoring_without_profile_and_does_not_book(self):
        manager, storage, bot, coordinator = self.build_manager([[self.slot], [self.slot]])

        response = await manager.start_search(self.chat_id, self.preferences)
        await wait_until(lambda: len(bot.messages) == 1)

        task = manager.state.tasks[self.chat_id]
        self.assertEqual(
            response,
            "Monitoring started: free play, all venues, 17:00-22:00, 2 places.",
        )
        self.assertFalse(task.done())
        self.assertEqual(len(bot.messages), 1)
        self.assertIn("Free PADL slots found", bot.messages[0]["text"])
        self.assertEqual(coordinator.reserve_calls, [])

        await manager.stop_search(self.chat_id)

    async def test_monitoring_does_not_repeat_same_slot_notification(self):
        manager, storage, bot, coordinator = self.build_manager([[self.slot], [self.slot]])

        await manager.start_search(self.chat_id, self.preferences)
        await wait_until(lambda: manager.scanner.calls >= 2)

        self.assertEqual(len(bot.messages), 1)
        self.assertEqual(
            storage.statuses[-1],
            (self.chat_id, True, "monitoring, no new slots"),
        )
        self.assertEqual(coordinator.reserve_calls, [])

        await manager.stop_search(self.chat_id)


if __name__ == "__main__":
    unittest.main()
