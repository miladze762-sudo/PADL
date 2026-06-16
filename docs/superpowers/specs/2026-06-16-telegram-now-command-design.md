# Telegram Current Slots Command Design

## Scope

Add a Telegram command `/now` that shows the slots available at the moment of the
request. The existing `/search` monitoring must keep running in the background and
must not lose its notification history.

## Behavior

`/now` uses the user's saved search preferences, runs one immediate scan, and
replies with all matching slots currently returned by the PADL API. If no matching
slots are available, it replies that there are no suitable free slots right now
and that monitoring continues.

The command does not start, stop, or restart monitoring. It does not mark slots as
already notified, reserve slots, request SMS, or change stored search state.

## Approach

Add a `SearchManager.current_slots_message(chat_id)` method that reads stored
preferences, calls the existing `SlotScanner.find_slots`, and formats the result
with the existing Telegram slot message formatter. Register `/now` in both
Telegram entry points:

- `padlbot/telegram_polling.py`
- `padlbot/telegram_app.py`

Update `/start` help and README command lists so users can discover `/now`.

## Testing

Add tests before implementation:

- service test proving `/now` returns the current slots without affecting
  monitoring notification state;
- Telegram polling test proving `/now` calls the manager and sends the response.

Run the targeted tests red, implement the minimal code, then run the full suite.
