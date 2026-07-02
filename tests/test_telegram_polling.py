import unittest
from unittest.mock import AsyncMock, patch

from padlbot.models import DEFAULT_DURATIONS, SearchPreferences
from padlbot.telegram_polling import (
    IncomingMessage,
    TelegramBot,
    handle_message,
    is_telegram_conflict_error,
    polling_loop,
)


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


class FakePollingBot:
    def __init__(self, batches):
        self.batches = list(batches)
        self.offsets = []
        self.deleted_webhooks = []
        self.messages = []

    async def get_updates(self, offset):
        self.offsets.append(offset)
        if not self.batches:
            raise RuntimeError("stop polling")
        return self.batches.pop(0)

    async def send_message(self, chat_id, text):
        self.messages.append({"chat_id": chat_id, "text": text})

    async def delete_webhook(self, *, drop_pending_updates):
        self.deleted_webhooks.append(drop_pending_updates)


class FakePollingStorage:
    def __init__(self, last_update_id=None):
        self.last_update_id = last_update_id
        self.saved_update_ids = []

    def get_preferences(self, chat_id):
        return SearchPreferences()

    def get_last_update_id(self):
        return self.last_update_id

    def save_last_update_id(self, update_id):
        self.last_update_id = update_id
        self.saved_update_ids.append(update_id)


class FakePollingManager:
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

    async def test_code_command_is_disabled_in_trigger_daemon_mode(self):
        bot = FakeBot()

        class CloudDisabledManager:
            runtime_mode = "trigger-daemon"

        await handle_message(
            IncomingMessage(chat_id=100, text="/code 1234"),
            bot=bot,
            manager=CloudDisabledManager(),
            storage=None,
        )

        self.assertEqual(
            bot.messages[0]["text"],
            "Автоматическое удержание слотов и СМС-подтверждение в облачном режиме отключены.",
        )


class TelegramPollingLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_polling_uses_persisted_offset_and_saves_after_success(self):
        bot = FakePollingBot(
            [
                [
                    {
                        "update_id": 100,
                        "message": {"chat": {"id": 200}, "text": "/search"},
                    }
                ]
            ]
        )
        storage = FakePollingStorage(last_update_id=99)
        manager = FakePollingManager()

        with patch("padlbot.telegram_polling.asyncio.sleep", new=AsyncMock(side_effect=RuntimeError("stop polling"))):
            with self.assertRaisesRegex(RuntimeError, "stop polling"):
                await polling_loop(bot=bot, manager=manager, storage=storage)

        self.assertEqual(bot.offsets[0], 100)
        self.assertEqual(storage.saved_update_ids, [100])

    async def test_polling_does_not_advance_offset_when_send_fails(self):
        batches = [
            [
                {
                    "update_id": 100,
                    "message": {"chat": {"id": 200}, "text": "/search"},
                }
            ]
        ]
        storage = FakePollingStorage()

        class FailingSendBot(FakePollingBot):
            async def send_message(self, chat_id, text):
                raise RuntimeError("send failed")

        bot = FailingSendBot(batches)

        sleep = AsyncMock(side_effect=[None, RuntimeError("stop polling")])
        with patch("padlbot.telegram_polling.asyncio.sleep", new=sleep):
            with self.assertRaisesRegex(RuntimeError, "stop polling"):
                await polling_loop(bot=bot, manager=FakePollingManager(), storage=storage)

        self.assertEqual(bot.offsets, [None, None])
        self.assertEqual(storage.saved_update_ids, [])

    async def test_delete_webhook_guard_calls_telegram_api(self):
        calls = []

        class FakeResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def json(self, content_type=None):
                return {"ok": True, "result": True}

        class FakeSession:
            def post(self, url, *, json):
                calls.append({"url": url, "json": json})
                return FakeResponse()

        bot = TelegramBot("token")
        bot.session = FakeSession()
        await bot.delete_webhook(drop_pending_updates=False)

        self.assertTrue(calls[0]["url"].endswith("/deleteWebhook"))
        self.assertEqual(calls[0]["json"], {"drop_pending_updates": False})

    async def test_telegram_conflict_exits_after_configured_threshold(self):
        statuses = []

        class ConflictBot(FakePollingBot):
            async def get_updates(self, offset):
                self.offsets.append(offset)
                raise RuntimeError("Telegram API error: {'error_code': 409, 'description': 'Conflict: terminated by other getUpdates request'}")

        bot = ConflictBot([])

        with self.assertRaisesRegex(RuntimeError, "Conflict"):
            await polling_loop(
                bot=bot,
                manager=FakePollingManager(),
                storage=FakePollingStorage(),
                on_polling_error=lambda status, error: statuses.append((status, error)),
                conflict_exit_seconds=0,
            )

        self.assertTrue(is_telegram_conflict_error(RuntimeError(statuses[0][1])))
        self.assertEqual(statuses[0][0], "conflict")


if __name__ == "__main__":
    unittest.main()
