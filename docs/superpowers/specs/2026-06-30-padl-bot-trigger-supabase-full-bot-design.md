# Спецификация полного PADL BOT через Trigger.dev и Supabase

Дата: 2026-06-30  
Статус: черновик для ревью  
Цель: подготовить PADL BOT к работе после `npm run trigger:deploy` так, чтобы Telegram-команды и автоматический мониторинг работали без локального `python -m padlbot`.

## Контекст

Текущий бот запускается локально как долгоживущий Python-процесс. Он держит Telegram long polling через `getUpdates`, запускает фоновые `asyncio`-циклы мониторинга и хранит состояние в локальной SQLite-базе `data/padlbot.db`.

Для Trigger Deploy такая модель не подходит как целевая: deployed task должен запускаться на конкретную работу и завершаться. Чтобы команды Telegram всё равно работали, нужен внешний публичный HTTP endpoint. В этой спецификации endpoint и durable database размещаются в Supabase:

- Supabase Edge Function принимает Telegram webhook.
- Supabase Postgres хранит состояние бота.
- Trigger.dev выполняет scheduled monitoring и Python-обработку команд.

Официальные опорные документы:

- Telegram Bot API: webhook и `X-Telegram-Bot-Api-Secret-Token`: https://core.telegram.org/bots/api#setwebhook
- Supabase Edge Functions подходят для webhook receivers и bot endpoints: https://supabase.com/docs/guides/functions
- Supabase Edge Function secrets доступны через env: https://supabase.com/docs/guides/functions/secrets
- Supabase Postgres connection guide: https://supabase.com/docs/guides/database/connecting-to-postgres
- Trigger.dev guide для запуска task из Supabase Edge Function: https://trigger.dev/docs/guides/frameworks/supabase-edge-functions-basic
- Trigger.dev Tasks API для внешнего запуска task: https://trigger.dev/docs/management/tasks/trigger
- Trigger.dev Python extension для запуска Python из deployed task: https://trigger.dev/docs/config/extensions/pythonExtension
- Supabase пример Telegram bot на Edge Functions: https://supabase.com/docs/guides/functions/examples/telegram-bot

## Целевой результат

После реализации будут работать два входа:

1. Telegram-команды через Supabase Edge Function.
2. Автоматический мониторинг через Trigger.dev scheduled task.

Целевая схема:

```text
Telegram
  -> Supabase Edge Function /telegram-webhook
  -> Supabase Postgres telegram_updates
  -> Trigger.dev task padl-bot-handle-telegram-update
  -> Python command handler
  -> Telegram sendMessage

Trigger.dev schedule padl-bot-scan-once
  -> Python scan runner
  -> Supabase Postgres state
  -> PADL API
  -> Telegram notifications
```

Команды `/start`, `/search`, `/stop`, `/status`, `/venues`, `/now` и `/profile` должны работать в Production. Команды legacy-бронирования `/code` и `/resend` в Trigger Deploy должны отвечать понятным сообщением, что автоматическое удержание и SMS-подтверждение отключены в облачном notification-only режиме.

## Не цели

- Не запускать `python -m padlbot` как вечный процесс внутри Trigger task.
- Не использовать Telegram long polling в Production.
- Не хранить Production-состояние в локальном SQLite-файле.
- Не реализовывать автоматическое бронирование, удержание слотов и SMS-подтверждение.
- Не делать отдельный пользовательский веб-интерфейс.

## Архитектура

### Supabase Edge Function

Создать функцию:

```text
supabase/functions/telegram-webhook/index.ts
```

Функция должна:

1. Принимать только `POST`.
2. Валидировать заголовок `X-Telegram-Bot-Api-Secret-Token`.
3. Парсить Telegram `Update`.
4. Проверять `chat_id` по allow-list, если Production-режим не объявлен публичным.
5. Сохранять update в таблицу `telegram_updates` через Supabase service/admin client.
6. Триггерить Trigger.dev task `padl-bot-handle-telegram-update` только если update еще не был успешно поставлен в очередь.
7. Записывать результат enqueue в `telegram_updates.enqueued_at`, `trigger_run_id`, `enqueue_attempts` и `last_enqueue_error`.
8. Возвращать `200 OK` быстро, без ожидания полного выполнения Python-команды, только когда update уже успешно поставлен в очередь, уже обработан или намеренно проигнорирован.

Функцию нужно деплоить как публичный webhook endpoint:

```powershell
supabase functions deploy telegram-webhook --no-verify-jwt
```

`--no-verify-jwt` нужен, потому что Telegram не отправляет Supabase JWT. Безопасность обеспечивается секретом Telegram webhook (`secret_token`) и проверкой заголовка.

Для вызова Trigger.dev из Supabase Edge Function использовать прямой HTTP вызов Tasks API через `fetch`, а не SDK, чтобы не зависеть от Node-only частей SDK в Deno runtime:

```text
POST https://api.trigger.dev/api/v1/tasks/padl-bot-handle-telegram-update/trigger
Authorization: Bearer TRIGGER_SECRET_KEY
```

Payload:

```json
{
  "payload": {
    "updateId": 123456789
  },
  "context": {},
  "options": {
    "idempotencyKey": "telegram-update-123456789"
  }
}
```

Критичный порядок операций:

1. Сначала idempotent insert/update в `telegram_updates`.
2. Затем вызов Trigger.dev с `idempotencyKey = telegram-update-<update_id>`.
3. Затем фиксация `enqueued_at` и `trigger_run_id`, если API вернул идентификатор run.

Если Supabase insert не удался, функция возвращает не-2xx, чтобы Telegram повторил webhook. Если insert удался, но Trigger API недоступен, функция увеличивает `enqueue_attempts`, сохраняет `last_enqueue_error` и тоже возвращает не-2xx. При повторе того же `update_id` функция не должна сразу гасить retry: если `enqueued_at IS NULL` и update не `ignored`, она повторяет enqueue. Это закрывает сценарий, где update уже сохранен в базе, но task еще не создан.

Если Trigger API успел создать run, а запись `enqueued_at` в Supabase упала, повторный webhook снова вызывает Trigger API с тем же `idempotencyKey`. Это допустимо: источник истины для дедупликации запуска - `update_id` в базе плюс idempotency key в Trigger.dev.

### Telegram webhook registration

После деплоя Supabase Function webhook регистрируется в Telegram:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook
```

Параметры:

```json
{
  "url": "https://<project-ref>.functions.supabase.co/telegram-webhook",
  "allowed_updates": ["message"],
  "secret_token": "<TELEGRAM_WEBHOOK_SECRET_TOKEN>",
  "drop_pending_updates": true
}
```

Пока webhook установлен, локальный `getUpdates` не будет получать updates. Для локального возврата к polling нужно удалить webhook через `deleteWebhook`.

### Trigger.dev tasks

`trigger.config.ts` должен явно подключать Python runtime:

- добавить зависимость `@trigger.dev/python`;
- подключить `pythonExtension` с копированием `padlbot/**/*.py` и `src/trigger/**/*.py`;
- устанавливать зависимости из `requirements.txt` через `requirementsFile`;
- оставить `runtime: "node"` и `dirs: ["./src/trigger"]`.

TypeScript task запускает Python только через `python.runScript(...)`. Обычный `subprocess`/shell из task не является целевым контрактом, потому что deploy build должен явно знать, какие Python-файлы и зависимости нужно упаковать.

Создать два основных task:

```text
padl-bot-handle-telegram-update
padl-bot-scan-once
```

`padl-bot-handle-telegram-update`:

- manual task;
- payload `{ updateId: number }`;
- `queue.concurrencyLimit: 1` для упорядоченной обработки команд;
- атомарно захватывает update из Supabase Postgres lease-операцией;
- запускает Python wrapper:

```text
src/trigger/run_padl_bot.py handle-update --update-id <id>
```

- Python handler обрабатывает команду и отправляет ответ в Telegram;
- обновляет `telegram_updates.status`;
- если update уже `handled`, `ignored` или находится в свежем `processing` lease, возвращает JSON summary `{"status":"ignored"}` без повторной отправки сообщения.

`padl-bot-scan-once`:

- scheduled task;
- cron `* * * * *`;
- timezone `Europe/Moscow`;
- `environments: ["PRODUCTION"]`;
- `queue.concurrencyLimit: 1`;
- запускает:

```text
src/trigger/run_padl_bot.py scan-once
```

- проверяет активные чаты и отправляет уведомления о новых слотах.

Дополнительно нужен recovery path для updates, которые сохранены, но не были поставлены в очередь из-за временной ошибки Trigger API. Минимальный вариант - документированная админ-команда или manual task:

```text
padl-bot-recover-telegram-updates
```

Она выбирает `telegram_updates` с `enqueued_at IS NULL`, `status IN ('received', 'failed')` и ограничением по `enqueue_attempts`, затем повторяет запуск `padl-bot-handle-telegram-update` с тем же `idempotencyKey`. Это не основной пользовательский entrypoint, а страховка на случай, если Telegram перестал повторять webhook до восстановления Trigger.dev.

### Python wrapper

Создать:

```text
src/trigger/run_padl_bot.py
```

Команды wrapper-а:

```text
scan-once
handle-update --update-id <telegram_update_id>
```

Wrapper добавляет корень проекта в `sys.path` и вызывает `padlbot.trigger_runner.main(args)`.

### Python trigger runner

Создать:

```text
padlbot/trigger_runner.py
```

Ответственности:

- `scan_once(config)`: один проход мониторинга по активным чатам.
- `handle_update(config, update_id)`: обработка одного Telegram update из Supabase.
- `send_message(chat_id, text)`: отправка ответа через текущий `TelegramBot`.
- `format JSON summary`: machine-readable итог в `stdout`.

Существующий `padlbot.telegram_polling.handle_message` завязан на объект `TelegramBot` и storage. Его надо не копировать целиком, а выделить общий command layer:

```text
padlbot/commands.py
```

Этот слой принимает `IncomingMessage`, storage, bot port и command services, затем возвращает/отправляет ответ. `telegram_polling.py`, `telegram_app.py` и `trigger_runner.py` используют один и тот же command layer.

Важно: cloud-обработчик команд не должен вызывать текущий `SearchManager.start_search()` как есть, потому что локальная реализация создает `asyncio.create_task(self._search_loop(...))` и рассчитана на долгоживущий процесс. Для общего слоя нужны две реализации backend-сервисов:

- `LocalCommandServices`: сохраняет текущее поведение локального polling и может запускать фоновые task внутри `python -m padlbot`.
- `TriggerCommandServices`: не запускает фоновых задач. `/search` только сохраняет preferences и `search_state.active = true`; `/stop` только деактивирует chat; `/now` выполняет один ограниченный по времени scan для текущего chat.

Trade-off: появляется дополнительная прослойка command services, зато одна и та же логика парсинга команд работает в polling, aiogram-dispatcher и Trigger, а cloud task гарантированно завершается.

## Supabase Postgres как durable database

Production storage должен быть Supabase Postgres. SQLite остается только для локального режима.

Добавить storage abstraction:

```text
padlbot/storage_base.py
padlbot/storage.py              # SQLite implementation
padlbot/storage_postgres.py     # Postgres implementation, Supabase-compatible
```

Config:

```text
PADL_STORAGE_BACKEND=sqlite|postgres
DATABASE_URL=<Supabase pooled/direct connection string>
```

Для Trigger.dev Production использовать `PADL_STORAGE_BACKEND=postgres`. Supabase здесь является провайдером Postgres, а не отдельным типом storage. Это сохраняет обратимость: при необходимости можно заменить Supabase на другой Postgres-compatible сервис без переименования backend-контракта.

### Таблицы

Сохранить текущую модель:

```text
profiles
preferences
search_state
last_bookings
```

Добавить:

```sql
CREATE TABLE IF NOT EXISTS telegram_updates (
  update_id BIGINT PRIMARY KEY,
  payload JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'received',
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  enqueue_attempts INTEGER NOT NULL DEFAULT 0,
  enqueued_at TIMESTAMPTZ,
  trigger_run_id TEXT,
  last_enqueue_error TEXT,
  processing_started_at TIMESTAMPTZ,
  processing_lease_until TIMESTAMPTZ,
  processed_at TIMESTAMPTZ,
  error TEXT
);

CREATE TABLE IF NOT EXISTS notified_slots (
  chat_id BIGINT NOT NULL,
  slot_key TEXT NOT NULL,
  venue_id INTEGER NOT NULL,
  court_id INTEGER NOT NULL,
  event_id INTEGER NOT NULL,
  starts_at TEXT NOT NULL,
  ends_at TEXT NOT NULL,
  duration_minutes INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  error TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_attempt_at TIMESTAMPTZ,
  retry_after TIMESTAMPTZ,
  sent_at TIMESTAMPTZ,
  notified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (chat_id, slot_key)
);
```

`telegram_updates` защищает от повторной обработки webhook retry и от потери update между Supabase insert и Trigger enqueue. `notified_slots` защищает от повторной отправки одного и того же слота.

Рекомендуемые индексы:

```sql
CREATE INDEX IF NOT EXISTS telegram_updates_recovery_idx
  ON telegram_updates (status, enqueued_at, received_at)
  WHERE enqueued_at IS NULL;

CREATE INDEX IF NOT EXISTS notified_slots_retry_idx
  ON notified_slots (status, retry_after)
  WHERE status = 'failed';
```

### Статусы

`telegram_updates.status`:

```text
received
processing
handled
failed
ignored
```

`notified_slots.status`:

```text
pending
sent
failed
```

Перед отправкой уведомления runner атомарно создает `pending`. После успешного Telegram `sendMessage` переводит запись в `sent`. Если Telegram упал, переводит в `failed`, сохраняет error и выставляет `retry_after`.

Повторная попытка разрешена только атомарным переходом:

```sql
UPDATE notified_slots
SET status = 'pending',
    attempt_count = attempt_count + 1,
    last_attempt_at = now(),
    error = NULL
WHERE chat_id = $1
  AND slot_key = $2
  AND status = 'failed'
  AND retry_after <= now()
RETURNING *;
```

Если записи нет, используется `INSERT ... ON CONFLICT DO NOTHING`. Если запись уже `pending` или `sent`, слот пропускается. Это убирает вечную блокировку failed slot при `PRIMARY KEY (chat_id, slot_key)`.

## Поведение Telegram-команд

### `/start`

Отправляет справку из `start_help_message()` и при необходимости создает дефолтные preferences для chat.

### `/search`

В Trigger Deploy сохраняет active monitoring без запуска фоновой `asyncio`-задачи:

```text
search_state.active = true
last_status = "мониторинг"
```

Отвечает пользователю, что мониторинг запущен. Ближайший scheduled `scan-once` пришлет новые слоты, если они есть. Не запускает бесконечный цикл.

### `/stop`

В Trigger Deploy ставит:

```text
search_state.active = false
last_status = "остановлен"
```

Следующие scheduled runs не проверяют этот chat. В локальном polling режиме `LocalCommandServices` дополнительно отменяет in-memory task, если он есть.

### `/status`

Читает `search_state`, последние настройки и последний результат. Отвечает текстом в текущем стиле проекта.

### `/venues`

Без аргументов показывает текущие площадки. С аргументами сохраняет `venue_ids` в `preferences`. `/venues all` возвращает дефолт.

### `/now`

Синхронно проверяет слоты только для этого chat и отвечает списком актуальных слотов. В Trigger Deploy эта команда должна иметь явный timeout меньше лимита task, например `REQUEST_TIMEOUT_SECONDS`. Не записывает слоты в `notified_slots`, чтобы `/now` не мешал будущим уведомлениям мониторинга.

### `/profile`

Сохраняет профиль как сейчас, но объясняет, что для notification-only мониторинга профиль не нужен.

### `/code` и `/resend`

В Trigger Deploy отвечают:

```text
Автоматическое удержание слота и SMS-подтверждение отключены в облачном режиме. Записывайтесь вручную на сайте PADL.
```

Это явнее и безопаснее, чем переносить pending booking state из памяти в базу в этой итерации.

## Env contract

### Supabase secrets

Для Edge Function:

```text
TRIGGER_SECRET_KEY
TELEGRAM_WEBHOOK_SECRET_TOKEN
SUPABASE_URL
SUPABASE_SECRET_KEYS
# fallback для старых проектов:
# SUPABASE_SERVICE_ROLE_KEY
```

`SUPABASE_URL` и service/admin key можно брать из Supabase project settings. Реализация должна предпочитать актуальный server-side secret JSON (`SUPABASE_SECRET_KEYS`, ключ `default`) и оставлять `SUPABASE_SERVICE_ROLE_KEY` только как fallback. Любой admin key используется только внутри Edge Function и не попадает в клиентский код.

Для личного Production-бота также задать:

```text
ALLOWED_CHAT_IDS=<telegram_chat_id>[,<telegram_chat_id>...]
```

Если бот намеренно публичный, это должно быть отдельным осознанным режимом, например `PUBLIC_BOT=1`. Иначе неизвестные `chat_id` сохраняются как `ignored`, webhook возвращает `200 OK`, а Trigger task не запускается.

### Trigger.dev Production env

```text
TELEGRAM_BOT_TOKEN
PADL_STORAGE_BACKEND=postgres
DATABASE_URL
PADL_SITE_BASE_URL=https://api.outdoor.sport.mos.ru
PADL_DEFAULT_VENUE_IDS=12,14,15
REQUEST_TIMEOUT_SECONDS=15
ALLOWED_CHAT_IDS=<telegram_chat_id>[,<telegram_chat_id>...]
```

Опционально:

```text
ADMIN_CHAT_ID
AUTO_START_SEARCH=1
```

`ADMIN_CHAT_ID` и `AUTO_START_SEARCH` нужны, если бот должен автоматически включить мониторинг для владельца без команды `/search`.

### Local `.env.example`

Обновить `.env.example`, чтобы были видны оба режима:

```text
PADL_STORAGE_BACKEND=sqlite
PADL_DB_PATH=data/padlbot.db

# Trigger/Supabase Production:
# PADL_STORAGE_BACKEND=postgres
# DATABASE_URL=postgresql://...
# TELEGRAM_WEBHOOK_SECRET_TOKEN=replace-me
# ALLOWED_CHAT_IDS=123456789
```

## Настройка Telegram webhook

Добавить документированный script или README-команду:

```powershell
$body = @{
  url = "https://<project-ref>.functions.supabase.co/telegram-webhook"
  allowed_updates = @("message")
  secret_token = $env:TELEGRAM_WEBHOOK_SECRET_TOKEN
  drop_pending_updates = $true
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN/setWebhook" `
  -ContentType "application/json" `
  -Body $body
```

Для локального polling:

```powershell
Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN/deleteWebhook"
```

## Ошибки и retry

### Telegram retry

Telegram повторяет webhook request, если endpoint вернул не-2xx. Поэтому Supabase Edge Function должна:

- валидный update сохранять idempotently;
- после успешного сохранения и запуска Trigger task возвращать `200 OK`;
- при повторе того же `update_id` возвращать `200 OK` только если `enqueued_at IS NOT NULL`, update уже `handled` или update `ignored`;
- при повторе сохраненного, но не enqueued update повторять Trigger enqueue, а не гасить retry.

Поведение duplicate webhook:

```text
status ignored                    -> 200 OK
enqueued_at present               -> 200 OK
status handled                    -> 200 OK
enqueued_at null, status received -> retry enqueue
enqueued_at null, status failed   -> retry enqueue, если лимит попыток не исчерпан
```

Если enqueue attempts исчерпаны, функция оставляет update в `failed` и возвращает 200 только после записи причины в `last_enqueue_error`; дальнейшее восстановление делает `padl-bot-recover-telegram-updates`.

### Trigger retry

`padl-bot-handle-telegram-update` должен быть идемпотентным:

- если `telegram_updates.status = handled`, task возвращает `ignored`;
- если `processing` зависло дольше `processing_lease_until`, task может попробовать заново;
- lease берется атомарным `UPDATE ... WHERE ... RETURNING`, чтобы две retry-попытки не обработали update одновременно;
- ошибки Python-команды сохраняются в `telegram_updates.error`.

`padl-bot-scan-once` должен быть идемпотентным через `notified_slots`.

### Недоступность PADL API

Scheduled task обновляет `search_state.last_status` временной ошибкой и завершает run. Следующий cron попробует снова.

### Недоступность Telegram sendMessage

Command task помечает update как `failed` и сохраняет error. Scheduled task помечает конкретные slot notifications как `failed`.

Для scheduled task `failed` notification не должна блокировать slot навсегда. Следующий run может повторить отправку только после `retry_after` и только если атомарно перевел запись из `failed` в `pending`. Это оптимизирует reliability ценой дополнительного состояния в таблице.

## Тестирование

### Python

- `tests/test_trigger_padl_bot_wrapper.py`: wrapper принимает `scan-once` и `handle-update`.
- `tests/test_trigger_runner.py`: `handle_update` обрабатывает `/start`, `/search`, `/stop`, `/status`, `/venues`, `/now`.
- `tests/test_trigger_runner.py`: повторный `update_id` не обрабатывается второй раз.
- `tests/test_trigger_runner.py`: `/search` в Trigger-режиме только сохраняет `search_state.active = true` и не создает `asyncio` background task.
- `tests/test_trigger_runner.py`: `scan_once` не дублирует `notified_slots`.
- `tests/test_trigger_runner.py`: failed notification становится eligible только после `retry_after`.
- `tests/test_storage_contract.py`: storage contract проходит для SQLite и fake/Postgres-compatible adapter.
- `tests/test_config.py`: `PADL_STORAGE_BACKEND=postgres` требует `DATABASE_URL`.
- `tests/test_commands.py`: общий command layer используется polling, aiogram-dispatcher и trigger runner без расхождения текстов команд.

### TypeScript

- `src/trigger/padlBotRuntime.test.ts`: env validation и task constants.
- `supabase/functions/telegram-webhook/index.test.ts`: проверка метода, secret header, allow-list, idempotent insert и Trigger API request.
- `supabase/functions/telegram-webhook/index.test.ts`: если insert прошел, а Trigger API упал, повторный webhook снова вызывает enqueue и не гасится как duplicate.
- `supabase/functions/telegram-webhook/index.test.ts`: unknown chat при закрытом боте получает `ignored` без запуска Trigger task.

### Интеграционные проверки

```powershell
python -m pytest
npm run test:trigger
npm run trigger:dry-run
npm run trigger:deploy
supabase functions deploy telegram-webhook --no-verify-jwt
```

После deploy:

1. `setWebhook` возвращает `ok: true`.
2. `/start` в Telegram создает запись в `telegram_updates` и получает ответ.
3. `/search` включает active monitoring.
4. `/status` показывает active state.
5. Scheduled run виден в Trigger.dev Dashboard.
6. Повторный scheduled run не дублирует уже отправленный slot.
7. Искусственный сбой Trigger API после сохранения update не теряет команду: recovery или повтор webhook создает run.

## Изменения в файлах

Создать:

- `supabase/functions/telegram-webhook/index.ts`
- `supabase/functions/telegram-webhook/index.test.ts`
- `supabase/migrations/<timestamp>_padl_bot_state.sql`
- `src/trigger/padlBot.ts`
- `src/trigger/padlBotRuntime.ts`
- `src/trigger/padlBotRuntime.test.ts`
- `src/trigger/run_padl_bot.py`
- `padlbot/commands.py`
- `padlbot/storage_base.py`
- `padlbot/storage_postgres.py`
- `padlbot/trigger_runner.py`
- `tests/test_commands.py`
- `tests/test_trigger_padl_bot_wrapper.py`
- `tests/test_trigger_runner.py`
- `tests/test_storage_contract.py`

Изменить:

- `package.json`
- `package-lock.json`
- `trigger.config.ts`
- `.env.example`
- `requirements.txt`
- `README.md`
- `README_RU.md`
- `padlbot/config.py`
- `padlbot/storage.py`
- `padlbot/telegram_app.py`
- `padlbot/telegram_polling.py`

Удалить:

- `src/trigger/example.ts`

## Миграция

Для первого Production запуска можно не переносить локальный SQLite, если владелец включит мониторинг через `/search` после настройки webhook.

Если нужно перенести текущее состояние:

1. Экспортировать `profiles`, `preferences`, `search_state`, `last_bookings` из `data/padlbot.db`.
2. Импортировать в Supabase Postgres.
3. Не импортировать старые in-memory notified slots, потому что они не являются durable сейчас.
4. После импорта выполнить `/status` и `/venues` в Telegram.

## Критерии готовности

- Supabase миграция создает все таблицы.
- Supabase Edge Function принимает Telegram webhook и валидирует secret header.
- Edge Function сохраняет update и запускает Trigger task без потери команды при сбое между insert и enqueue.
- Unknown chat в закрытом Production-режиме не запускает Trigger task.
- `padl-bot-handle-telegram-update` отвечает на основные Telegram-команды.
- `/search` в Trigger-режиме не запускает бесконечный loop и только включает durable active state.
- `padl-bot-scan-once` работает по расписанию и отправляет уведомления.
- Supabase Postgres сохраняет active chats, preferences, incoming updates и notified slots.
- Повторные Telegram webhook retries и Trigger retries не создают дублей и не теряют update.
- `notified_slots.failed` повторяется после `retry_after`, а `sent` никогда не отправляется второй раз.
- Локальный `python -m padlbot` продолжает работать через SQLite после `deleteWebhook`.

## Риски

- Команды будут отвечать с небольшой задержкой, потому что Edge Function только ставит задачу, а ответ отправляет Trigger task.
- Если Trigger.dev недоступен, webhook вернет не-2xx после сохранения update, Telegram будет повторять запрос; если retry прекратятся, recovery task должен дозапустить update.
- Supabase Free tier может быть достаточен для личного бота, но частый cron в Trigger.dev может выйти за бесплатные credits.
- Полный перенос legacy SMS booking state не входит в эту спецификацию.
- Allow-list защищает личного бота от чужих чатов, но требует заранее знать `chat_id`. Публичный режим проще для onboarding, но добавляет abuse/rate-limit риски.

## Решение

ADR: Full webhook mode через Supabase + Trigger.dev.

### Context

MVP Trigger Deploy может запускать только scheduled monitoring. Для Production-паритета Telegram-команд нужен публичный HTTPS ingress, потому что Trigger task сам по себе не заменяет Telegram webhook endpoint. Текущий Python-код при `/search` запускает in-memory loop, поэтому cloud-команды должны отделить durable state changes от локальных фоновых задач.

### Options

1. Scheduled-only MVP.
   - Оптимизирует deployability и скорость реализации.
   - Жертвует interactive Telegram-командами в Production.
   - Effort: low.
   - Reversibility: high.

2. Full webhook mode через Supabase Edge Function и Postgres.
   - Оптимизирует functional parity и отсутствие локального процесса.
   - Жертвует простотой: появляются enqueue/recovery, leases, allow-list и Postgres contract.
   - Effort: medium/high.
   - Reversibility: medium, потому что storage abstraction оставляет путь назад к SQLite локально и к другому Postgres-провайдеру в Production.

### Decision

Выбрать вариант 2 как целевой full-bot design, но реализовывать его поверх уже описанного scheduled-only MVP. Supabase отвечает за публичный Telegram endpoint и durable state, Trigger.dev отвечает за worker/orchestrator слой, Python сохраняет бизнес-логику через общий command layer.

Trade-off: платим дополнительной сложностью таблиц и retry-протокола, чтобы убрать зависимость от локального процесса и сохранить Telegram-команды после `npm run trigger:deploy`.

### Migration path

1. Сначала внедрить Postgres storage contract и scheduled `scan-once`.
2. Затем вынести общий `padlbot/commands.py` и разделить `LocalCommandServices`/`TriggerCommandServices`.
3. Затем добавить `telegram_updates`, Supabase Edge Function и `padl-bot-handle-telegram-update`.
4. Затем включить Telegram webhook и выполнить ручные проверки `/start`, `/search`, `/status`, `/now`.
5. После стабилизации включить recovery task для старых `enqueued_at IS NULL` updates.

### Revisit trigger

Пересмотреть архитектуру, если:

- средняя задержка ответа на Telegram-команды превышает 10 секунд;
- recovery task находит больше 1% не-enqueued updates за сутки;
- Trigger/Supabase стоимость или лимиты становятся выше приемлемых для личного бота;
- появляется требование вернуть автоматическое бронирование и SMS state в облако.

### Fitness functions

- `supabase/functions/telegram-webhook/index.test.ts` моделирует `insert ok -> Trigger API fail -> duplicate webhook -> enqueue ok`.
- `tests/test_trigger_runner.py` доказывает, что `/search` в Trigger-режиме не создает `asyncio` background task.
- `tests/test_storage_contract.py` доказывает одинаковое поведение SQLite и Postgres для `preferences`, `search_state`, `telegram_updates`, `notified_slots`.
- `npm run trigger:dry-run` доказывает, что Trigger build содержит Python files и зависимости из `requirements.txt`.
- Интеграционная проверка повторного scheduled run доказывает, что `sent` slot не отправляется второй раз, а `failed` retry работает только после `retry_after`.
