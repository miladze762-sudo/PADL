import unittest

from padlbot.models import DEFAULT_DURATIONS, SearchPreferences
from padlbot.telegram_polling import IncomingMessage, handle_message


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text):
        self.messages.append({"chat_id": chat_id, "text": text})


class FakeNowManager:
    def __init__(self):
        self.calls = []

    async def current_slots_message(self, chat_id):
        self.calls.append(chat_id)
        return "current slots"


class FakeSearchStorage:
    def __init__(self):
        self.preferences = SearchPreferences(
            start_time="17:00",
            end_time="22:00",
            tickets_count=1,
            durations=(60,),
            venue_ids=(12,),
            target_dates=("2026-06-12",),
            event_type="masterclass",
        )

    def get_preferences(self, chat_id):
        return self.preferences


class FakeVenueStorage:
    def __init__(self, preferences=None):
        self.preferences = preferences or SearchPreferences(venue_ids=(12,), poll_interval_seconds=7)
        self.saved_preferences = []

    def get_preferences(self, chat_id):
        return self.preferences

    def save_preferences(self, chat_id, preferences):
        self.preferences = preferences
        self.saved_preferences.append((chat_id, preferences))


class FakeSearchManager:
    def __init__(self):
        self.calls = []

    async def start_search(self, chat_id, preferences):
        self.calls.append((chat_id, preferences))
        return "started"


class TelegramPollingMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_message_is_russian(self):
        bot = FakeBot()

        await handle_message(
            IncomingMessage(chat_id=100, text="/start"),
            bot=bot,
            manager=None,
            storage=None,
        )

        self.assertEqual(
            bot.messages[0]["text"],
            "Бот PADL готов.\n\n"
            "Запустить постоянный мониторинг: /search\n"
            "Бот ищет без ограничения по времени.\n"
            "Записывайтесь вручную на сайте PADL:\n"
            "https://outdoor.sport.mos.ru/#venues-events\n"
            "Площадки: /venues\n"
            "Другие команды: /now, /status, /stop",
        )
        self.assertNotIn("1.", bot.messages[0]["text"])
        self.assertNotIn("2.", bot.messages[0]["text"])
        self.assertIn("Площадки: /venues", bot.messages[0]["text"])
        self.assertIn("Другие команды: /now, /status, /stop", bot.messages[0]["text"])

    async def test_venues_command_saves_selected_venues(self):
        bot = FakeBot()
        storage = FakeVenueStorage()

        await handle_message(
            IncomingMessage(chat_id=100, text="/venues 14,15"),
            bot=bot,
            manager=None,
            storage=storage,
        )

        self.assertEqual(storage.saved_preferences[0][0], 100)
        saved = storage.saved_preferences[0][1]
        self.assertEqual(saved.venue_ids, (14, 15))
        self.assertEqual(saved.poll_interval_seconds, 7)
        self.assertEqual(
            bot.messages[0]["text"],
            "Площадки сохранены: Третьяковская, Римская.",
        )

    async def test_venues_command_without_args_lists_current_and_available_venues(self):
        bot = FakeBot()
        storage = FakeVenueStorage(SearchPreferences(venue_ids=(14,)))

        await handle_message(
            IncomingMessage(chat_id=100, text="/venues"),
            bot=bot,
            manager=None,
            storage=storage,
        )

        self.assertEqual(
            bot.messages[0]["text"],
            "Текущие площадки: Третьяковская.\n\n"
            "Изменить: /venues 12,14\n"
            "Все площадки: /venues all\n"
            "Доступные площадки:\n"
            "12 - Баррикадная\n"
            "14 - Третьяковская\n"
            "15 - Римская",
        )

    async def test_venues_all_restores_default_venues(self):
        bot = FakeBot()
        storage = FakeVenueStorage(SearchPreferences(venue_ids=(14,)))

        await handle_message(
            IncomingMessage(chat_id=100, text="/venues all"),
            bot=bot,
            manager=None,
            storage=storage,
        )

        saved = storage.saved_preferences[0][1]
        self.assertEqual(saved.venue_ids, (12, 14, 15))
        self.assertEqual(bot.messages[0]["text"], "Площадки сохранены: все площадки.")

    async def test_venues_command_rejects_unknown_venue(self):
        bot = FakeBot()
        storage = FakeVenueStorage()

        await handle_message(
            IncomingMessage(chat_id=100, text="/venues 99"),
            bot=bot,
            manager=None,
            storage=storage,
        )

        self.assertEqual(storage.saved_preferences, [])
        self.assertEqual(
            bot.messages[0]["text"],
            "Неизвестная площадка: 99. Доступны: 12, 14, 15.",
        )

    async def test_profile_usage_message_is_russian(self):
        bot = FakeBot()

        await handle_message(
            IncomingMessage(chat_id=100, text="/profile Ivan"),
            bot=bot,
            manager=None,
            storage=None,
        )

        self.assertEqual(
            bot.messages[0]["text"],
            "Формат: /profile ИМЯ ФАМИЛИЯ ТЕЛЕФОН ПОЧТА",
        )

    async def test_unknown_command_message_is_russian(self):
        bot = FakeBot()

        await handle_message(
            IncomingMessage(chat_id=100, text="/wat"),
            bot=bot,
            manager=None,
            storage=None,
        )

        self.assertEqual(
            bot.messages[0]["text"],
            "Неизвестная команда. Отправьте /start для справки.",
        )

    async def test_now_command_sends_current_slots(self):
        bot = FakeBot()
        manager = FakeNowManager()

        await handle_message(
            IncomingMessage(chat_id=100, text="/now"),
            bot=bot,
            manager=manager,
            storage=None,
        )

        self.assertEqual(manager.calls, [100])
        self.assertEqual(bot.messages[0]["text"], "current slots")

    async def test_search_uses_default_free_play_preferences_and_saved_venues(self):
        bot = FakeBot()
        manager = FakeSearchManager()

        await handle_message(
            IncomingMessage(chat_id=100, text="/search 2026-06-20 18:00-19:00"),
            bot=bot,
            manager=manager,
            storage=FakeSearchStorage(),
        )

        self.assertEqual(bot.messages[0]["text"], "started")
        self.assertEqual(manager.calls[0][0], 100)
        preferences = manager.calls[0][1]
        self.assertIsNone(preferences.start_time)
        self.assertIsNone(preferences.end_time)
        self.assertEqual(preferences.target_dates, ())
        self.assertEqual(preferences.tickets_count, 2)
        self.assertEqual(preferences.durations, DEFAULT_DURATIONS)
        self.assertEqual(preferences.venue_ids, (12,))
        self.assertEqual(preferences.event_type, "free_play")


if __name__ == "__main__":
    unittest.main()
