# PADL BOT Presentation Design

## Goal

Prepare a Russian visual presentation that explains how PADL BOT works as a system:
what problem it solves, how the user starts it, how Telegram commands trigger monitoring,
how the bot checks PADL availability, and what the bot deliberately does not automate.

## Audience

The presentation is for a mixed audience: a user or stakeholder should understand the
workflow without reading code, while a technical reader should still see the main
components and data flow.

## Recommended Format

Create a self-contained HTML slide deck:

- File: `PADL_BOT_PRESENTATION_RU.html`
- Language: Russian
- Layout: widescreen presentation-style sections
- Style: clear, restrained, operational, with diagrams and compact explanations
- Dependencies: no external runtime dependencies for viewing the file

HTML is preferred because the project already benefits from browser-based visual review,
and the slide deck can include simple diagrams without requiring PowerPoint or extra tools.

## Slide Structure

1. `PADL BOT: назначение`
   Explain that the bot monitors free PADL slots on `outdoor.sport.mos.ru` and sends
   Telegram notifications.

2. `Проблема и сценарий пользователя`
   Explain that slots appear unpredictably, so the bot repeatedly checks availability
   instead of making the user refresh the site manually.

3. `Главная архитектура`
   Show the flow: Telegram user -> PADL BOT -> PADL API -> Telegram notification.

4. `Запуск программы`
   Show `.env`, virtual environment, and `python -m padlbot` as the startup path.

5. `Команды Telegram`
   Explain `/start`, `/search`, `/now`, `/status`, and `/stop`.

6. `Цикл мониторинга`
   Show the loop: read preferences, request availability, filter slots, notify only about
   new slots, sleep for about 15 seconds, repeat.

7. `Критерии поиска`
   Show default venues, event type, ticket count, duration priorities, and no time limit.

8. `Хранение состояния`
   Explain that SQLite stores profiles, preferences, search state, and last booking data.

9. `Что бот не делает`
   Make the safety boundary explicit: the current `/search` flow does not automatically
   book, hold slots, bypass SMS, or confirm appointments.

10. `Ошибки и диагностика`
    Cover missing Telegram token, `chat not found`, duplicate bot instance, network/API
    errors, and terminal dry-run checking.

11. `Итог`
    Summarize the value: the bot saves attention by monitoring continuously and quickly
    reporting new available slots; the user still books manually on PADL.

## Visual Elements

- System flow diagram for Telegram, bot process, PADL API, database, and user notification.
- Monitoring cycle diagram with repeated checks.
- Command cards for the main Telegram commands.
- Clear warning/limitation panel for non-automated booking behavior.
- Small troubleshooting grid for common operational problems.

## Out Of Scope

- Building a new bot feature.
- Changing search behavior.
- Adding automatic booking.
- Exposing tokens or real private chat IDs.
- Creating a PowerPoint file unless requested later.

## Acceptance Criteria

- The presentation can be opened locally in a browser.
- The presentation uses the approved "working system scheme" direction.
- The slide deck contains the 11 approved slides.
- The wording is simple Russian, suitable for non-developers.
- The deck accurately states that current monitoring only notifies and does not book slots.
