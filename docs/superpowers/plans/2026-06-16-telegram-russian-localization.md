# Telegram Russian Localization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Telegram-visible bot message Russian while keeping command names unchanged.

**Architecture:** The bot has two Telegram entry points: `telegram_polling.py` and `telegram_app.py`. Shared user-facing slot and booking text lives in `formatting.py`, while operational responses come from `service.py` and booking errors from `booking.py`.

**Tech Stack:** Python 3, `unittest`, `aiohttp` polling, optional `aiogram` dispatcher.

---

### Task 1: Update Text Expectations First

**Files:**
- Modify: `tests/test_formatting.py`
- Modify: `tests/test_service.py`

- [ ] **Step 1: Write failing expectations**

Change formatting tests to expect Russian labels such as `Корт:` and monitoring
headers such as `Найдены свободные слоты PADL`.

Change service tests to expect Russian start/status strings:

```python
"Мониторинг запущен: free play, все площадки, 17:00-22:00, мест: 2."
```

- [ ] **Step 2: Run focused tests to verify failure**

Run:

```powershell
python -m unittest tests.test_formatting tests.test_service
```

Expected: FAIL because production strings are still English.

### Task 2: Translate Shared Formatting And Service Responses

**Files:**
- Modify: `padlbot/formatting.py`
- Modify: `padlbot/service.py`
- Modify: `padlbot/booking.py`

- [ ] **Step 1: Implement minimal translations**

Translate slot labels, monitoring headers, booking confirmations, status output,
SMS-related user errors, and booking errors that can reach Telegram.

- [ ] **Step 2: Run focused tests**

Run:

```powershell
python -m unittest tests.test_formatting tests.test_service
```

Expected: PASS.

### Task 3: Translate Telegram Command Handlers

**Files:**
- Modify: `padlbot/telegram_polling.py`
- Modify: `padlbot/telegram_app.py`

- [ ] **Step 1: Translate direct command replies**

Translate `/start`, `/profile`, `/code`, `/resend`, unknown-command help, and
validation errors. Keep slash command names unchanged.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
python -m unittest discover tests
```

Expected: PASS.

### Task 4: Scan For Remaining Telegram-Facing English

**Files:**
- Inspect: `padlbot/*.py`

- [ ] **Step 1: Search remaining English user-facing text**

Run:

```powershell
rg -n '"[^"]*[A-Za-z][^"]*"' padlbot
```

Review remaining English strings and keep only commands, API keys, logs, internal
exceptions, or protocol/database values.

- [ ] **Step 2: Final verification**

Run:

```powershell
python -m unittest discover tests
```

Expected: PASS.
