# Telegram Russian Localization Design

## Scope

Translate all Telegram-facing bot messages to Russian while keeping command names unchanged:
 `/start`, `/profile`, `/search`, `/status`, `/stop`, `/code`, and `/resend`.

## Approach

Update user-visible strings in the Telegram command handlers, formatting helpers,
booking error messages, and search manager status output. Keep API payload keys,
database column names, environment variables, and internal protocol values as-is.

## Files

- `padlbot/telegram_app.py`
- `padlbot/telegram_polling.py`
- `padlbot/formatting.py`
- `padlbot/service.py`
- `padlbot/booking.py`
- Related tests that assert Telegram-visible text.

## Testing

Update the existing tests first so they expect Russian output, run them to confirm
the current English implementation fails, then update production code and run the
full test suite.
