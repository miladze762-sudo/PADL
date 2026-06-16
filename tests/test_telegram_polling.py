import unittest

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


class TelegramPollingMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_message_is_russian(self):
        bot = FakeBot()

        await handle_message(
            IncomingMessage(chat_id=100, text="/start"),
            bot=bot,
            manager=None,
            storage=None,
        )

        self.assertIn("Бот PADL готов.", bot.messages[0]["text"])
        self.assertIn("/search 17:00-22:00", bot.messages[0]["text"])
        self.assertIn("/now", bot.messages[0]["text"])

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


if __name__ == "__main__":
    unittest.main()
