# Unbounded Search Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/search` monitor all matching PADL free slots without time or date limits.

**Architecture:** Represent an unbounded time window by allowing `SearchPreferences.start_time` and `end_time` to be `None`. Keep storage backward compatible, normalize Telegram `/search` preferences so old arguments are ignored, and update user-facing text to describe one persistent monitoring mode.

**Tech Stack:** Python dataclasses, sqlite storage, unittest, aiohttp Telegram polling, optional aiogram dispatcher.

---

### Task 1: Make Slot Selection Time-Unbounded

**Files:**
- Modify: `padlbot/models.py`
- Modify: `padlbot/selection.py`
- Test: `tests/test_selection.py`

- [ ] **Step 1: Write the failing test**

Add a test that uses default `SearchPreferences()` and expects slots before and
after the old evening window to be accepted when duration and tickets match.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m unittest tests.test_selection.SelectionTests.test_extract_candidates_allows_any_time_when_window_is_unset`

Expected: FAIL because the current default still filters to `17:00-22:00`.

- [ ] **Step 3: Implement minimal model and selection change**

Change `SearchPreferences.start_time` and `end_time` to `str | None = None`.
Make `_inside_window` return `True` when either boundary is not set.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `python -m unittest tests.test_selection.SelectionTests.test_extract_candidates_allows_any_time_when_window_is_unset`

Expected: PASS.

### Task 2: Normalize Telegram `/search` To One Mode

**Files:**
- Modify: `padlbot/telegram_polling.py`
- Modify: `padlbot/telegram_app.py`
- Test: `tests/test_telegram_polling.py`

- [ ] **Step 1: Write the failing polling test**

Add a fake storage and manager assertion proving `/search 2026-06-20 18:00-19:00`
calls `start_search` with `start_time is None`, `end_time is None`, and empty
`target_dates`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m unittest tests.test_telegram_polling.TelegramPollingMessageTests.test_search_ignores_time_and_date_arguments`

Expected: FAIL because the current handler parses those arguments into preferences.

- [ ] **Step 3: Implement minimal Telegram changes**

Remove the `/search` argument parsing from both Telegram entry points. When the
command runs, copy stored preferences while setting `start_time=None`,
`end_time=None`, and `target_dates=()`.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `python -m unittest tests.test_telegram_polling.TelegramPollingMessageTests.test_search_ignores_time_and_date_arguments`

Expected: PASS.

### Task 3: Update Service Text, Docs, And Compatibility

**Files:**
- Modify: `padlbot/service.py`
- Modify: `padlbot/storage.py`
- Modify: `padlbot/formatting.py`
- Modify: `README_RU.md`
- Modify: `README.md`
- Modify: `RUNNING_BOT_RU.md`
- Modify: `SETUP_STATUS_RU.md`
- Modify: `INSTALL_FOR_USER_RU.md`
- Test: `tests/test_service.py`
- Test: `tests/test_storage.py`
- Test: `tests/test_telegram_polling.py`

- [ ] **Step 1: Update failing expectations**

Change service and Telegram tests to expect `/search` and "без ограничения по
времени" instead of `17:00-22:00`.

- [ ] **Step 2: Implement text and storage compatibility**

Allow storage to persist `None` time boundaries as empty strings and read empty
strings back as `None`. Update start/help/legacy text and docs.

- [ ] **Step 3: Run focused tests**

Run: `python -m unittest tests.test_selection tests.test_telegram_polling tests.test_service tests.test_storage`

Expected: PASS.

- [ ] **Step 4: Run full verification**

Run: `python -m unittest discover`

Expected: PASS.
