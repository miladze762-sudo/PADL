# Unbounded Search Monitoring Design

## Goal

Make `/search` start continuous PADL monitoring without a user-facing time window
or target date filter. The bot should simply watch all free-play slots returned by
the PADL booking horizon and notify about new matching free slots until `/stop`.

## Scope

Keep the existing command set: `/now`, `/status`, `/stop`, `/profile`, `/code`,
and `/resend` remain available. This change only removes the time/date narrowing
from the `/search` monitoring path and user-facing documentation.

The remaining filters stay unchanged:

- PADL venues configured in `SearchPreferences.venue_ids`.
- Event type `free_play`.
- Ticket count from preferences, currently 2 by default.
- Duration priority from preferences, currently 120, 90, then 60 minutes.

## Behavior

`/search` should work with no arguments and should ignore old-style arguments such
as `/search 17:00-22:00` or `/search 2026-06-20 17:00-22:00`. Starting a new search
must store preferences with no time window and no target dates, so old saved date
or time settings do not keep narrowing future monitoring.

Slot extraction should accept matching slots at any time of day when no time
window is configured. Date filtering remains supported internally for tests and
non-Telegram callers only if preferences explicitly set `target_dates`.

User-facing help and docs should present `/search` as the only start command,
without examples that include dates or time windows. Start/status text should say
"without time limits" or equivalent Russian wording instead of showing
`17:00-22:00`.

## Testing

Add tests that fail under the current implementation:

- Selection accepts a valid free slot outside `17:00-22:00` when preferences have
  no time window.
- Telegram polling `/search 18:00-19:00` starts monitoring with unbounded
  preferences and clears `target_dates`.
- Service start response describes monitoring without time limits.

Run the focused tests, then the full unit test suite.
