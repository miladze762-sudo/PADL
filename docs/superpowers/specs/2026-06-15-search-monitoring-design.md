# Search Monitoring Design

## Goal

Change the bot so `/search` becomes a continuous notification-only monitor for free
PADL slots. The monitor runs indefinitely until the user sends `/stop` or the bot
process stops. The bot must not hold slots, send SMS requests, verify SMS codes, or
confirm bookings from `/search`. The user will register manually on the PADL site
after receiving a Telegram notification.

## User Flow

1. User sends `/search 17:00-22:00` or `/search 2026-06-20 17:00-22:00`.
2. Bot stores the search preferences and starts a continuous background monitoring loop.
3. On every poll, bot scans the same venues and slot filters as today.
4. If new matching slots appear, bot sends them to Telegram.
5. Already-notified slots are suppressed so the same slot is not sent repeatedly.
6. User sends `/status` to see whether monitoring is active.
7. User sends `/stop` to stop monitoring.

## Behavior

`/search` no longer requires a saved profile. Profile data remains available only for
legacy booking/SMS commands, but the monitoring path does not use it.

The monitor keeps running after a slot is found and does not stop on successful
notifications. It sends only slots that have not already been reported during the
active run. A slot is unique by venue, court, event, start time, end time, and
duration.

When no slots are available, the bot stays quiet and records status as
`monitoring, no matching slot yet`. When new slots are sent, status records how many
new slots were found in the last poll.

Temporary scan errors should not stop monitoring. The bot records a temporary error
status and retries after the configured poll interval.

## Notifications

For each new batch, the bot sends a concise message:

`Free PADL slots found. Register manually on the site:`

Then it lists the slot details using the existing slot formatter. If several new
slots are found in one poll, the bot sends them together in one message when the
message length allows it. If needed, the implementation may split long batches into
multiple Telegram messages.

## Commands

`/search` starts continuous monitoring and replaces the previous booking flow.

`/status` reports active/inactive monitoring, the last status text, and any last
confirmed booking that may still be stored from older runs.

`/stop` cancels the active monitoring task and clears in-memory notification state
for that chat.

`/code` and `/resend` may remain in the code for older pending bookings, but they are
not part of the new `/search` flow.

## Data Flow

`Telegram polling -> SearchManager.start_search -> SearchManager._search_loop ->
SlotScanner.find_slots -> TelegramBot.send_message`

The booking coordinator must not be called from the `/search` monitoring path.

## Testing

Add service-level tests that prove:

- `/search` can start without a saved profile.
- New slots are announced through Telegram.
- The same slot is not announced again on the next poll.
- The monitor continues after announcing a slot.
- Booking methods are not called from the monitoring path.

Update Telegram command tests or direct handler tests if existing coverage depends on
the old profile-required `/search` behavior.
