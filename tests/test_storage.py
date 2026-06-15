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


if __name__ == "__main__":
    unittest.main()
