# PADL BOT

Telegram bot for continuous monitoring of free padel slots on `outdoor.sport.mos.ru`.
The runtime uses `aiohttp` for both Telegram polling and the site API.

## What It Does

- Checks all three venues for `free_play` slots.
- Uses the default target: any available day, `17:00-22:00`, 2 places, duration preference `120 -> 90 -> 60`.
- Sends Telegram notifications when new matching free slots appear.
- Keeps monitoring after notifications and suppresses repeated messages for the same slot during the active run.
- Does not hold slots, request SMS, or confirm bookings from `/search`; register manually on the PADL site.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`:

- `TELEGRAM_BOT_TOKEN`: token from BotFather.
- `ADMIN_CHAT_ID`: your Telegram chat id. This is useful when the SMS forwarder does not send `chat_id`.
- `SMS_FORWARD_SECRET` and `PADL_DRY_RUN` are not needed for `/search` monitoring.

Run:

```powershell
python -m padlbot
```

## Telegram Commands

- `/start` - show setup help.
- `/profile FIRST LAST PHONE EMAIL` - save an old booking profile if needed for legacy SMS commands.
- `/search 17:00-22:00` - start continuous monitoring for any day in the site's booking horizon.
- `/search 2026-06-12 17:00-22:00` - monitor a specific date.
- `/now` - show slots available right now without stopping monitoring.
- `/status` - show current state and last booking.
- `/stop` - stop active monitoring.
- `/code 1234` - legacy manual SMS fallback for an already-held slot.

## Legacy Android SMS Forwarder

The new `/search` monitoring flow does not need SMS forwarding. This endpoint remains
only for old already-held booking flows.

During local testing, configure the Android forwarder to POST to:

```text
http://YOUR_PC_LOCAL_IP:8080/sms
```

JSON body:

```json
{
  "secret": "same-value-as-SMS_FORWARD_SECRET",
  "text": "SMS text with code 4821",
  "chat_id": 123456789
}
```

If `ADMIN_CHAT_ID` is set in `.env`, `chat_id` can be omitted.

## Terminal Availability Check

`/search` is always notification-only and keeps monitoring until `/stop`.

To test availability from the terminal:

```powershell
python scripts\dry_run.py
```

## VPS Move

On VPS, install the same requirements, copy `.env`, and run `python -m padlbot`.
