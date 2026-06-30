# PADL BOT Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained Russian HTML slide deck that visually explains how PADL BOT works.

**Architecture:** Create one standalone HTML file at the repository root. The file contains embedded CSS, eleven slide sections, simple diagrams, command cards, troubleshooting panels, and no external dependencies.

**Tech Stack:** Static HTML and CSS; PowerShell for local file checks; optional browser preview through the existing visual companion URL.

---

## File Structure

- Create: `PADL_BOT_PRESENTATION_RU.html`
  - Responsibility: final presentation, usable by opening the file in a browser.
- Reference: `docs/superpowers/specs/2026-06-19-padl-bot-presentation-design.md`
  - Responsibility: approved slide structure and acceptance criteria.
- No Python bot code changes are needed.

## Task 1: Create The Slide Deck

**Files:**
- Create: `PADL_BOT_PRESENTATION_RU.html`
- Reference: `docs/superpowers/specs/2026-06-19-padl-bot-presentation-design.md`

- [x] **Step 1: Create a standalone HTML document**

Create `PADL_BOT_PRESENTATION_RU.html` with:

```html
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PADL BOT: презентация по работе программы</title>
  <style>
    body { margin: 0; font-family: Arial, sans-serif; background: #f4f7fb; color: #142033; }
    .deck { max-width: 1180px; margin: 0 auto; padding: 24px; }
    .slide { min-height: 720px; background: #fff; margin: 0 0 24px; padding: 56px; border-radius: 18px; }
  </style>
</head>
<body>
  <main class="deck">
    <section class="slide">
      <p class="eyebrow">PADL BOT</p>
      <h1>Презентация по работе программы</h1>
      <p>Как бот мониторит свободные слоты PADL и отправляет уведомления в Telegram.</p>
    </section>
  </main>
</body>
</html>
```

Expected: the file opens without any network dependency.

- [x] **Step 2: Add all approved slides**

Include these exact slide topics in Russian:

```text
1. PADL BOT: назначение
2. Проблема и сценарий пользователя
3. Главная архитектура
4. Запуск программы
5. Команды Telegram
6. Цикл мониторинга
7. Критерии поиска
8. Хранение состояния
9. Что бот не делает
10. Ошибки и диагностика
11. Итог
```

Expected: `Select-String -Pattern '<section class="slide"' PADL_BOT_PRESENTATION_RU.html` finds 11 slides.

- [x] **Step 3: Add visual system explanations**

Add these visual blocks:

```text
Telegram -> PADL BOT -> API PADL -> Telegram notification
Monitoring loop: preferences -> API request -> filtering -> new-slot check -> notification -> sleep 15 seconds
Command cards: /start, /search, /now, /status, /stop
Limitations panel: no auto booking, no slot holding, no SMS bypass, no confirmation
Troubleshooting grid: token, chat not found, duplicate instance, network/API, dry run
```

Expected: a non-developer can follow the flow without reading Python files.

## Task 2: Verify The Deck

**Files:**
- Check: `PADL_BOT_PRESENTATION_RU.html`

- [x] **Step 1: Check file exists and is non-empty**

Run:

```powershell
Get-Item -LiteralPath 'PADL_BOT_PRESENTATION_RU.html' | Select-Object Name,Length
```

Expected: file exists and `Length` is greater than `10000`.

- [x] **Step 2: Check approved slide count**

Run:

```powershell
(Select-String -LiteralPath 'PADL_BOT_PRESENTATION_RU.html' -Pattern '<section class="slide"').Count
```

Expected: `11`.

- [x] **Step 3: Check key safety wording**

Run:

```powershell
Select-String -LiteralPath 'PADL_BOT_PRESENTATION_RU.html' -Pattern 'не бронирует|не удерживает|СМС|вручную'
```

Expected: output includes the limitation slide wording that the bot only notifies and booking is manual.

- [x] **Step 4: Preview visually**

Copy the presentation into the visual companion content directory as a fresh HTML file or open it locally in a browser.

Expected: slides are readable, visually structured, and match the approved "working system scheme" direction.
