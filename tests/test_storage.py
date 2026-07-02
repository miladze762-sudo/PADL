import unittest
from pathlib import Path

from padlbot.models import Profile, SearchPreferences
from padlbot.storage import Storage


class StorageTests(unittest.TestCase):
    def test_profile_round_trip(self):
        db_path = Path.cwd() / "test-profile.db"
        try:
            storage = Storage(db_path)
            storage.initialize()
            profile = Profile(
                chat_id=100,
                first_name="Ivan",
                last_name="Ivanov",
                phone="+79161234567",
                email="ivan@example.com",
            )

            storage.save_profile(profile)

            self.assertEqual(storage.get_profile(100), profile)
        finally:
            db_path.unlink(missing_ok=True)

    def test_preferences_round_trip(self):
        db_path = Path.cwd() / "test-preferences.db"
        try:
            storage = Storage(db_path)
            storage.initialize()
            preferences = SearchPreferences(
                start_time="18:00",
                end_time="21:30",
                tickets_count=2,
                durations=(120, 60),
                venue_ids=(14, 12),
            )

            storage.save_preferences(100, preferences)

            self.assertEqual(storage.get_preferences(100), preferences)
        finally:
            db_path.unlink(missing_ok=True)

    def test_preferences_without_time_window_round_trip(self):
        db_path = Path.cwd() / "test-preferences-unbounded.db"
        try:
            storage = Storage(db_path)
            storage.initialize()
            preferences = SearchPreferences(
                start_time=None,
                end_time=None,
                tickets_count=2,
                durations=(120, 60),
                venue_ids=(14, 12),
                target_dates=(),
            )

            storage.save_preferences(100, preferences)

            self.assertEqual(storage.get_preferences(100), preferences)
        finally:
            db_path.unlink(missing_ok=True)

    def test_list_active_search_chat_ids(self):
        db_path = Path.cwd() / "test-active-searches.db"
        try:
            storage = Storage(db_path)
            storage.initialize()
            storage.set_search_active(100, True, "monitoring")
            storage.set_search_active(200, False, "stopped")
            storage.set_search_active(300, True, "monitoring")

            self.assertEqual(storage.list_active_search_chat_ids(), [100, 300])
        finally:
            db_path.unlink(missing_ok=True)

    def test_telegram_polling_state_round_trip(self):
        db_path = Path.cwd() / "test-polling-state.db"
        try:
            storage = Storage(db_path)
            storage.initialize()

            self.assertIsNone(storage.get_last_update_id())
            storage.save_last_update_id(123456)

            self.assertEqual(storage.get_last_update_id(), 123456)
        finally:
            db_path.unlink(missing_ok=True)

    def test_notified_slots_suppress_duplicates_after_restart(self):
        db_path = Path.cwd() / "test-notified-slots.db"
        try:
            storage = Storage(db_path)
            storage.initialize()

            self.assertTrue(storage.mark_slot_notified(100, "slot-1"))
            self.assertFalse(storage.mark_slot_notified(100, "slot-1"))
            self.assertTrue(storage.mark_slot_notified(100, "slot-2"))
        finally:
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
