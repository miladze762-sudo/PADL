# Telegram Now Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/now`, a one-shot Telegram command that shows currently available PADL slots without interrupting ongoing monitoring.

**Architecture:** `SearchManager` will expose a small query method that reuses the existing `SlotScanner` and slot formatters. Both Telegram entry points will call that method for `/now`; persistent monitoring state and notified-slot tracking remain owned by `/search`.

**Tech Stack:** Python 3, `unittest`, `aiohttp` polling, optional `aiogram` dispatcher.

---

### Task 1: Add Current-Snapshot Service Behavior

**Files:**
- Modify: `tests/test_service.py`
- Modify: `padlbot/service.py`

- [ ] **Step 1: Write the failing service test**

Add this test to `SearchManagerMonitoringTests` in `tests/test_service.py`:

```python
    async def test_current_slots_message_lists_slots_without_marking_notified(self):
        manager, storage, bot, coordinator = self.build_manager([[self.slot]])
        manager.state.notified_slots[self.chat_id] = set()

        response = await manager.current_slots_message(self.chat_id)

        self.assertIn("Актуальные свободные слоты PADL прямо сейчас", response)
        self.assertIn("Площадка: Третьяковская", response)
        self.assertEqual(manager.state.notified_slots[self.chat_id], set())
        self.assertEqual(bot.messages, [])
        self.assertEqual(coordinator.reserve_calls, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest tests.test_service.SearchManagerMonitoringTests.test_current_slots_message_lists_slots_without_marking_notified
```

Expected: FAIL with `AttributeError` because `SearchManager.current_slots_message` does not exist.

- [ ] **Step 3: Write minimal service implementation**

Add `current_slots_message` to `SearchManager` in `padlbot/service.py`:

```python
    async def current_slots_message(self, chat_id: int) -> str:
        preferences = self.storage.get_preferences(chat_id)
        slots = await self.scanner.find_slots(preferences)
        if not slots:
            return "Сейчас подходящих свободных слотов нет. Мониторинг продолжается."
        messages = format_monitoring_slot_messages(
            slots,
            preferences.tickets_count,
            header="Актуальные свободные слоты PADL прямо сейчас:",
        )
        return "\n\n".join(messages)
```

Update `format_monitoring_slot_messages` in `padlbot/formatting.py` to accept the optional `header` parameter without changing current callers:

```python
def format_monitoring_slot_messages(
    slots: list[SlotCandidate],
    tickets_count: int,
    max_message_length: int = TELEGRAM_MESSAGE_LIMIT,
    header: str = "Найдены свободные слоты PADL. Запишитесь вручную на сайте:",
) -> list[str]:
```

- [ ] **Step 4: Run focused service test**

Run:

```powershell
python -m unittest tests.test_service.SearchManagerMonitoringTests.test_current_slots_message_lists_slots_without_marking_notified
```

Expected: PASS.

### Task 2: Wire `/now` Into Telegram Polling

**Files:**
- Modify: `tests/test_telegram_polling.py`
- Modify: `padlbot/telegram_polling.py`

- [ ] **Step 1: Write the failing polling test**

Add a fake manager and test in `tests/test_telegram_polling.py`:

```python
class FakeNowManager:
    def __init__(self):
        self.calls = []

    async def current_slots_message(self, chat_id):
        self.calls.append(chat_id)
        return "current slots"
```

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest tests.test_telegram_polling.TelegramPollingMessageTests.test_now_command_sends_current_slots
```

Expected: FAIL because `/now` is treated as an unknown command.

- [ ] **Step 3: Implement polling command**

Add `/now` handling to `padlbot/telegram_polling.py` before the unknown command branch:

```python
    if command == "/now":
        try:
            response = await manager.current_slots_message(message.chat_id)
        except Exception as exc:
            response = str(exc)
        await bot.send_message(message.chat_id, response)
        return
```

Add `/now` to the `/start` command list.

- [ ] **Step 4: Run focused polling test**

Run:

```powershell
python -m unittest tests.test_telegram_polling.TelegramPollingMessageTests.test_now_command_sends_current_slots
```

Expected: PASS.

### Task 3: Wire `/now` Into Aiogram And Docs

**Files:**
- Modify: `padlbot/telegram_app.py`
- Modify: `README.md`
- Modify: `README_RU.md`

- [ ] **Step 1: Implement aiogram command**

Add this handler to `padlbot/telegram_app.py` near `/status`:

```python
    @dp.message(Command("now"))
    async def now(message: Message):
        try:
            response = await manager.current_slots_message(message.chat.id)
        except Exception as exc:
            response = str(exc)
        await message.answer(response)
```

Add `/now` to the aiogram `/start` help.

- [ ] **Step 2: Update README command lists**

Add `/now` to English and Russian command lists as the command for showing
currently available slots without stopping monitoring.

- [ ] **Step 3: Run full test suite**

Run:

```powershell
python -m unittest discover tests
```

Expected: PASS.
