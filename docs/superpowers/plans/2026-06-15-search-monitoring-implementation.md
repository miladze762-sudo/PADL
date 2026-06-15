# Search Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/search` run as a continuous notification-only monitor for free PADL slots.

**Architecture:** Keep the existing `SearchManager` task loop, but change the `/search` path so it scans and notifies instead of booking. Track notified slot keys in memory per chat to prevent repeated Telegram spam during the active run.

**Tech Stack:** Python 3, `asyncio`, `unittest`, existing `SlotScanner`, existing Telegram polling handlers.

---

## File Structure

- Modify `padlbot/service.py`: remove the profile requirement from `start_search`, add per-chat notified slot state, and make `_search_loop` continuously announce new slots without calling booking methods.
- Modify `padlbot/formatting.py`: add a small helper for manual-registration monitoring notifications.
- Modify `padlbot/telegram_polling.py`: update `/start` text so `/search` is described as monitoring.
- Modify `padlbot/telegram_app.py`: keep aiogram help text consistent with polling help text.
- Modify `README_RU.md` and `README.md`: document notification-only monitoring at a high level.
- Modify `tests/test_service.py`: add async service tests for profile-free continuous monitoring, notification suppression, and no booking calls.

### Task 1: Monitoring Tests

**Files:**
- Modify: `tests/test_service.py`

- [ ] **Step 1: Write failing service tests**

Add fake storage, scanner, bot, and coordinator objects in `tests/test_service.py`. Add tests that start `_search_loop` through `start_search`, wait until one or two scan calls happen, then stop the task.

The tests should assert:

```python
self.assertEqual(response, "Monitoring started: free play, all venues, 17:00-22:00, 2 places.")
self.assertEqual(len(bot.messages), 1)
self.assertIn("Free PADL slots found", bot.messages[0]["text"])
self.assertEqual(coordinator.reserve_calls, [])
self.assertTrue(task.done() is False before stop)
```

Add a second test where the scanner returns the same slot twice:

```python
self.assertEqual(len(bot.messages), 1)
self.assertEqual(storage.statuses[-1], (chat_id, True, "monitoring, no new slots"))
```

- [ ] **Step 2: Run tests and verify red**

Run: `python -m unittest tests.test_service -v`

Expected: FAIL because the old implementation requires a profile and calls booking behavior after finding a slot.

### Task 2: Formatting Helper

**Files:**
- Modify: `padlbot/formatting.py`

- [ ] **Step 1: Add `format_monitoring_slots`**

Add:

```python
def format_monitoring_slots(slots: list[SlotCandidate], tickets_count: int) -> str:
    slot_lines = []
    for index, slot in enumerate(slots, start=1):
        slot_lines.append(f"{index}.\\n" + format_slot(slot, tickets_count))
    return (
        "Free PADL slots found. Register manually on the site:\\n\\n"
        + "\\n\\n".join(slot_lines)
    )
```

- [ ] **Step 2: Run focused tests**

Run: `python -m unittest tests.test_service -v`

Expected: still FAIL until service behavior is changed.

### Task 3: Continuous Search Loop

**Files:**
- Modify: `padlbot/service.py`

- [ ] **Step 1: Add notified slot state**

Extend `RuntimeState`:

```python
notified_slots: dict[int, set[tuple]]
```

Initialize it in `RuntimeState.empty()`.

- [ ] **Step 2: Change `start_search`**

Remove the profile lookup and profile error. Save preferences, set state to active, reset notified slots for the chat, create the task, and return:

```python
"Monitoring started: free play, all venues, "
f"{preferences.start_time}-{preferences.end_time}, "
f"{preferences.tickets_count} places"
...
```

- [ ] **Step 3: Change `_search_loop`**

Replace hold/SMS/booking logic with:

```python
slots = await self.scanner.find_slots(preferences)
new_slots = self._new_slots_for_notification(chat_id, slots)
if new_slots:
    await self.bot.send_message(
        chat_id,
        format_monitoring_slots(new_slots, preferences.tickets_count),
    )
    self.storage.set_search_active(
        chat_id,
        True,
        f"monitoring, {len(new_slots)} new slot(s) found",
    )
else:
    status = "monitoring, no matching slot yet" if not slots else "monitoring, no new slots"
    self.storage.set_search_active(chat_id, True, status)
await asyncio.sleep(preferences.poll_interval_seconds)
```

- [ ] **Step 4: Add `_new_slots_for_notification`**

Add a helper that uses `_slot_key` to suppress duplicates and updates `state.notified_slots[chat_id]`.

- [ ] **Step 5: Update stop cleanup**

Make `stop_search` also remove `self.state.notified_slots[chat_id]`.

- [ ] **Step 6: Run tests and verify green**

Run: `python -m unittest tests.test_service -v`

Expected: PASS.

### Task 4: Command and Docs Text

**Files:**
- Modify: `padlbot/telegram_polling.py`
- Modify: `padlbot/telegram_app.py`
- Modify: `README_RU.md`
- Modify: `README.md`

- [ ] **Step 1: Update Telegram help text**

Change `/start` text so it says:

```text
Start monitoring: /search 17:00-22:00
The bot only notifies you about free slots. Register manually on the PADL site.
```

- [ ] **Step 2: Update README files**

Update descriptions so they no longer claim `/search` automatically books from the main flow. Keep legacy SMS commands documented only as older/manual fallback behavior if still mentioned.

- [ ] **Step 3: Run all tests**

Run: `python -m unittest discover -v`

Expected: PASS.

## Notes

This workspace has no `.git` directory, so plan steps do not include commits.

