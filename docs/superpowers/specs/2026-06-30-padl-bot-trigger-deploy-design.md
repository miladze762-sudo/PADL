# Спецификация Trigger Deploy для PADL BOT

Дата: 2026-06-30  
Статус: черновик для ревью  
Цель: подготовить PADL BOT к запуску через `npm run trigger:deploy`, чтобы мониторинг работал в Trigger.dev Production без локального `python -m padlbot`.

## Контекст

Сейчас основная программа запускается как долгоживущий Python-процесс `python -m padlbot`. Этот процесс одновременно держит Telegram long polling, SMS webhook, `asyncio`-задачи мониторинга и локальную SQLite-базу `data/padlbot.db`.

В репозитории уже есть каркас Trigger.dev: `package.json`, `trigger.config.ts`, `src/trigger/example.ts` и проект `proj_idvrbofrajznnafltimb`. По примеру `C:\Users\Admin\Desktop\Note Doom` целевой паттерн должен быть таким: TypeScript task в `src/trigger` запускает маленький Python-wrapper через `@trigger.dev/python`, а wrapper импортирует основной Python-код.

Главное отличие Trigger Deploy от локального процесса: deployed task должен быстро выполнить работу и завершиться. Нельзя считать локальный SQLite-файл, Telegram polling и память процесса постоянными между cloud-run. Поэтому мониторинг переносится из бесконечного цикла в stateless `scan-once`, а состояние дедупликации и активных чатов выносится в durable storage.

## Целевой результат

После реализации и `npm run trigger:deploy` в Trigger.dev Production должен появиться один основной scheduled task:

```text
Task: padl-bot-scan-once
Schedule: * * * * *
Timezone: Europe/Moscow
Environment: PRODUCTION
Concurrency: 1
```

Каждый запуск task:

1. Загружает Production env.
2. Поднимает Python runtime через `@trigger.dev/python`.
3. Запускает `src/trigger/run_padl_bot.py scan-once`.
4. Python-код проверяет PADL API по активным настройкам мониторинга.
5. Отправляет в Telegram только новые слоты.
6. Сохраняет ключи отправленных слотов в durable storage.
7. Возвращает в Trigger.dev summary: сколько чатов проверено, сколько слотов найдено, сколько уведомлений отправлено, какие ошибки были временными.

## Не цели

- Не переносить текущий `python -m padlbot` как бесконечный процесс внутрь Trigger task.
- Не сохранять зависимость от локального `data/padlbot.db` для Production.
- Не возобновлять автоматическое удержание слота, SMS и подтверждение брони. Deploy-режим остается notification-only.
- Не делать полноценный UI или отдельный веб-сервис в этой итерации.
- Не требовать поддержки `trigger dev`; спецификация оптимизирована под `trigger deploy`.

## Архитектура

### Trigger layer

`trigger.config.ts` должен перейти на паттерн из `Note Doom`:

- добавить зависимость `@trigger.dev/python`;
- подключить `pythonExtension`;
- копировать Python-файлы `padlbot/**/*.py` и `src/trigger/**/*.py`;
- устанавливать `requirements.txt` через `requirementsFile`;
- оставить `runtime: "node"`, `dirs: ["./src/trigger"]`, `maxDuration` и retries.

Ссылки на официальные docs Trigger.dev:

- `pythonExtension` копирует Python scripts, ставит `requirementsFile` в production build и позволяет запускать `python.runScript`: https://trigger.dev/docs/config/extensions/pythonExtension
- `schedules.task()` предназначен для recurring cron tasks: https://trigger.dev/docs/tasks/scheduled
- `trigger deploy` строит и публикует текущую версию tasks в Trigger.dev Cloud; env vars для deployed tasks задаются в Dashboard или sync extension: https://trigger.dev/docs/deployment/overview

### TypeScript task

Создать `src/trigger/padlBot.ts`:

- экспортирует `schedules.task({ id: "padl-bot-scan-once", ... })`;
- не пытается задавать cron через runtime env: declarative schedule фиксируется в коде как `* * * * *`;
- задает `timezone: "Europe/Moscow"` и `environments: ["PRODUCTION"]`;
- задает `queue.concurrencyLimit: 1`, чтобы два сканирования не отправляли одинаковые слоты одновременно;
- задает `ttl: "1m"` или `"2m"`, чтобы старые scheduled runs не копились;
- вызывает `python.runScript("./src/trigger/run_padl_bot.py", ["scan-once"], { env })`;
- логирует `stdout` как info, `stderr` как warn;
- возвращает JSON-результат без секретов.

Файл `src/trigger/example.ts` удалить, чтобы в Dashboard не оставался demo task.

### TypeScript runtime helper

Создать `src/trigger/padlBotRuntime.ts`:

- хранит constants `PADL_BOT_TASK_ID`, `PADL_BOT_TIMEZONE`, `PADL_BOT_CRON`;
- собирает env для Python из `process.env`;
- валидирует обязательные переменные;
- нормализует числовые env (`ADMIN_CHAT_ID`, `REQUEST_TIMEOUT_SECONDS`);
- запрещает случайное использование локального `PADL_DB_PATH=data/padlbot.db` в Production, если выбран durable backend;
- не печатает secret values.

Для PADL BOT не нужны base64 file secrets, в отличие от `Note Doom`, потому что Telegram token и PADL settings являются обычными env vars. Если позже появятся file secrets, использовать тот же подход, что в `Note Doom`: base64 env -> временный файл -> путь в Python env.

### Python wrapper

Создать `src/trigger/run_padl_bot.py`:

- добавляет корень репозитория в `sys.path`;
- принимает команду `scan-once`;
- вызывает `padlbot.trigger_runner.main(args)`;
- возвращает exit code `0` при успешном run, ненулевой только при конфигурационной ошибке или полностью невосстановимом сбое.

### Python runner

Создать `padlbot/trigger_runner.py`:

- `scan_once(config: Config) -> ScanResult`;
- инициализирует storage;
- при `AUTO_START_SEARCH=1` и `ADMIN_CHAT_ID` гарантирует активный мониторинг для admin chat;
- получает активные `chat_id`;
- для каждого `chat_id` загружает preferences, приводит их к текущему unbounded search-режиму;
- через `OutdoorApiClient` и `SlotScanner` находит слоты;
- фильтрует уже отправленные слоты через durable storage;
- отправляет новые сообщения через `TelegramBot.send_message`;
- сохраняет отправленные slot keys после успешной отправки;
- обновляет `search_state.last_status`;
- печатает machine-readable JSON summary в `stdout`.

Логика форматирования сообщений переиспользует `format_monitoring_slot_messages`. Логика выбора площадок и слотов переиспользует `SearchPreferences`, `SlotScanner`, `selection`, `venues`.

## Durable storage

Текущий `Storage` на SQLite остается для локального запуска. Для Trigger Deploy нужен новый backend, потому что filesystem cloud-run не должен быть источником истины.

Рекомендуемый backend: Postgres-compatible database с `DATABASE_URL`, например Supabase или Neon.

Добавить интерфейсный слой:

- `padlbot/storage_base.py` с протоколом методов, которые нужны runner-у;
- текущий `Storage` остается SQLite-реализацией;
- новая реализация `PostgresStorage` использует `DATABASE_URL`;
- `Config.from_env()` выбирает backend по `PADL_STORAGE_BACKEND=sqlite|postgres`.

Минимальный набор таблиц для Production:

```text
profiles
preferences
search_state
last_bookings
notified_slots
```

Новая таблица `notified_slots`:

```text
chat_id BIGINT NOT NULL
slot_key TEXT NOT NULL
venue_id INTEGER NOT NULL
court_id INTEGER NOT NULL
event_id INTEGER NOT NULL
starts_at TEXT NOT NULL
ends_at TEXT NOT NULL
notified_at TIMESTAMPTZ NOT NULL DEFAULT now()
status TEXT NOT NULL DEFAULT 'pending'
error TEXT
PRIMARY KEY (chat_id, slot_key)
```

`slot_key` должен совпадать с текущим `SearchManager._slot_key`: venue, court, event, start, end, duration. Вставка должна быть атомарной (`INSERT ... ON CONFLICT DO NOTHING`), чтобы concurrency guard был и в базе, и в Trigger queue.

Для локального SQLite тоже добавить `notified_slots`, чтобы тесты и dry-run поведение совпадали.

## Telegram-поведение

Trigger Deploy MVP работает как scheduled notifier:

- бот отправляет уведомления в активные чаты;
- `/search`, `/stop`, `/venues`, `/status` через Telegram long polling не запускаются в Trigger Production;
- активный admin monitoring включается через `AUTO_START_SEARCH=1` и `ADMIN_CHAT_ID`;
- настройки площадок можно задать заранее через storage seed или env `PADL_DEFAULT_VENUE_IDS`.

Полный паритет Telegram-команд возможен отдельной итерацией через Telegram webhook ingress:

1. публичный HTTPS endpoint принимает Telegram update;
2. endpoint валидирует `X-Telegram-Bot-Api-Secret-Token`;
3. endpoint вызывает Trigger task `padl-bot-handle-telegram-update`;
4. Python переиспользует `handle_message`.

Эта итерация не входит в MVP, потому что чистый Trigger task не заменяет публичный HTTP-сервер для Telegram webhook без дополнительного ingress-слоя. Для текущей цели важнее надежный deployed monitoring.

## Env contract

Production env в Trigger.dev:

```text
TELEGRAM_BOT_TOKEN
ADMIN_CHAT_ID
PADL_STORAGE_BACKEND=postgres
DATABASE_URL
PADL_SITE_BASE_URL=https://api.outdoor.sport.mos.ru
AUTO_START_SEARCH=1
PADL_DEFAULT_VENUE_IDS=12,14,15
REQUEST_TIMEOUT_SECONDS=15
```

Оставить, но не считать обязательными для Trigger Deploy MVP:

```text
SMS_FORWARD_SECRET
SMS_WEBHOOK_HOST
SMS_WEBHOOK_PORT
PADL_DRY_RUN
PADL_LOCK_HOST
PADL_LOCK_PORT
```

Локальный `.env.example` должен описывать оба режима:

- `PADL_STORAGE_BACKEND=sqlite` для локального `python -m padlbot`;
- `PADL_STORAGE_BACKEND=postgres` и `DATABASE_URL` для Trigger Deploy.

## Ошибки и retry

Config errors должны падать явно: нет `TELEGRAM_BOT_TOKEN`, нет `ADMIN_CHAT_ID` при `AUTO_START_SEARCH=1`, нет `DATABASE_URL` при `PADL_STORAGE_BACKEND=postgres`.

Сетевые ошибки PADL API или Telegram считаются временными:

- runner записывает ошибку в summary;
- обновляет `last_status`;
- завершает run без бесконечного цикла;
- Trigger retries могут повторить run по текущей retry policy.

Если сообщение в Telegram отправлено, а запись `notified_slots` упала, следующий run может отправить этот slot повторно. Чтобы снизить риск, порядок должен быть:

1. атомарно зарезервировать notification через `notified_slots`;
2. отправить Telegram message;
3. если отправка упала, пометить запись как failed или удалить reservation для будущей попытки.

Для этого в MVP используется status в `notified_slots`:

```text
status TEXT NOT NULL DEFAULT 'pending'
error TEXT
```

Переходы:

- `pending` перед отправкой;
- `sent` после успешной отправки;
- `failed` при ошибке Telegram, чтобы будущий run мог повторить после cooldown.

## Тестирование

Python tests:

- wrapper `src/trigger/run_padl_bot.py` строит default args и импортирует `padlbot`;
- `trigger_runner.scan_once` отправляет только новые слоты;
- повторный `scan_once` не отправляет уже сохраненные slot keys;
- `AUTO_START_SEARCH=1` создает active search для `ADMIN_CHAT_ID`;
- storage contract tests проходят и для SQLite, и для fake/Postgres adapter;
- config tests покрывают `PADL_STORAGE_BACKEND`, `DATABASE_URL`, `PADL_DEFAULT_VENUE_IDS`.

TypeScript tests:

- `padlBotRuntime.ts` валидирует env;
- task constants совпадают с ожидаемыми id/cron/timezone;
- helper не раскрывает secret values;
- `npm run test:trigger` запускает Node tests через `tsx`.

Deploy checks:

```powershell
python -m pytest
npm run test:trigger
npm run trigger:dry-run
npm run trigger:deploy
```

После deploy:

- Dashboard показывает `padl-bot-scan-once`;
- schedule активен в Production;
- manual test run возвращает JSON summary;
- Telegram получает test notification только при новом слоте или через controlled fake/test mode.

## Изменения в файлах

Создать:

- `src/trigger/padlBot.ts`
- `src/trigger/padlBotRuntime.ts`
- `src/trigger/padlBotRuntime.test.ts`
- `src/trigger/run_padl_bot.py`
- `padlbot/trigger_runner.py`
- `padlbot/storage_base.py`
- `padlbot/storage_postgres.py`
- `tests/test_trigger_padl_bot_wrapper.py`
- `tests/test_trigger_runner.py`
- `tests/test_storage_contract.py`

Изменить:

- `package.json`
- `package-lock.json`
- `trigger.config.ts`
- `.env.example`
- `requirements.txt`
- `padlbot/config.py`
- `padlbot/storage.py`
- `README.md`
- `README_RU.md`

Удалить:

- `src/trigger/example.ts`

## Миграция данных

Для MVP можно не мигрировать локальный `data/padlbot.db`, если `AUTO_START_SEARCH=1`, `ADMIN_CHAT_ID` и `PADL_DEFAULT_VENUE_IDS` достаточно задают рабочий мониторинг.

Если нужно сохранить пользовательские preferences:

1. экспортировать `preferences` и `search_state` из SQLite;
2. импортировать их в Postgres;
3. проверить, что `list_active_search_chat_ids()` возвращает ожидаемые chat ids;
4. только после этого включать Production schedule.

## Критерии готовности

- `npm run trigger:dry-run` успешно строит проект с Python extension.
- `npm run trigger:deploy` публикует версию с одним настоящим task, без demo task.
- Trigger.dev Production env содержит все обязательные переменные.
- Scheduled run выполняет `scan-once` и завершается.
- Состояние дедупликации сохраняется в Postgres между runs.
- Повторный run не дублирует Telegram-уведомления о том же slot.
- Локальный запуск `python -m padlbot` остается работоспособным с `PADL_STORAGE_BACKEND=sqlite`.

## Риски

- Частота текущего локального polling `15` секунд не совпадает с cron-моделью Trigger MVP. Начальная частота будет раз в минуту.
- Без отдельного Telegram webhook ingress в Production не будет полного interactive command mode.
- Postgres backend добавляет внешний сервис, который нужно создать и поддерживать.
- Ошибки между reservation и Telegram send требуют аккуратной обработки `pending/failed/sent`, иначе возможны пропуски или дубли.

## Решение

Реализовать Trigger Deploy как scheduled `scan-once`, а не как перенос бесконечного Python-процесса. Это соответствует модели Trigger.dev, повторяет удачный Python/TypeScript-паттерн из `Note Doom`, сохраняет основной Python-код проекта и делает Production monitoring устойчивым к перезапускам cloud-run.
