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
4. Сохранять update в таблицу `telegram_updates` через Supabase service/admin client.
5. Триггерить Trigger.dev task `padl-bot-handle-telegram-update`.
6. Возвращать `200 OK` быстро, без ожидания полного выполнения Python-команды.

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

Создать два основных task:

```text
padl-bot-handle-telegram-update
padl-bot-scan-once
```

`padl-bot-handle-telegram-update`:

- manual task;
- payload `{ updateId: number }`;
- `queue.concurrencyLimit: 1` для упорядоченной обработки команд;
- загружает update из Supabase Postgres;
- запускает Python wrapper:

```text
src/trigger/run_padl_bot.py handle-update --update-id <id>
```

- Python handler обрабатывает команду и отправляет ответ в Telegram;
- обновляет `telegram_updates.status`.

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

Этот слой принимает `IncomingMessage`, storage, bot port и scanner/manager services, затем возвращает/отправляет ответ. `telegram_polling.py` и `trigger_runner.py` используют один и тот же command layer.

## Supabase Postgres как durable database

Production storage должен быть Supabase Postgres. SQLite остается только для локального режима.

Добавить storage abstraction:

```text
padlbot/storage_base.py
padlbot/storage.py              # SQLite implementation
padlbot/storage_supabase.py     # Postgres implementation
```

Config:

```text
PADL_STORAGE_BACKEND=sqlite|supabase
DATABASE_URL=<Supabase pooled/direct connection string>
```

Для Trigger.dev Production использовать `PADL_STORAGE_BACKEND=supabase`.

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
  processing_started_at TIMESTAMPTZ,
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
  notified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (chat_id, slot_key)
);
```

`telegram_updates` защищает от повторной обработки webhook retry. `notified_slots` защищает от повторной отправки одного и того же слота.

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

Перед отправкой уведомления runner атомарно создает `pending`. После успешного Telegram `sendMessage` переводит запись в `sent`. Если Telegram упал, переводит в `failed` и сохраняет error, чтобы следующий run мог повторить после cooldown.

## Поведение Telegram-команд

### `/start`

Отправляет справку из `start_help_message()` и при необходимости создает дефолтные preferences для chat.

### `/search`

Сохраняет active monitoring:

```text
search_state.active = true
last_status = "мониторинг"
```

Отвечает пользователю, что мониторинг запущен. Ближайший scheduled `scan-once` пришлет новые слоты, если они есть. Не запускает бесконечный цикл.

### `/stop`

Ставит:

```text
search_state.active = false
last_status = "остановлен"
```

Следующие scheduled runs не проверяют этот chat.

### `/status`

Читает `search_state`, последние настройки и последний результат. Отвечает текстом в текущем стиле проекта.

### `/venues`

Без аргументов показывает текущие площадки. С аргументами сохраняет `venue_ids` в `preferences`. `/venues all` возвращает дефолт.

### `/now`

Синхронно проверяет слоты только для этого chat и отвечает списком актуальных слотов. Не записывает их в `notified_slots`, чтобы `/now` не мешал будущим уведомлениям мониторинга.

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
SUPABASE_SERVICE_ROLE_KEY
```

`SUPABASE_URL` и service/admin key можно брать из Supabase project settings. Если проект уже использует новые default secrets `SUPABASE_SECRET_KEYS`, implementation может предпочесть их и оставить `SUPABASE_SERVICE_ROLE_KEY` fallback-ом.

### Trigger.dev Production env

```text
TELEGRAM_BOT_TOKEN
PADL_STORAGE_BACKEND=supabase
DATABASE_URL
PADL_SITE_BASE_URL=https://api.outdoor.sport.mos.ru
PADL_DEFAULT_VENUE_IDS=12,14,15
REQUEST_TIMEOUT_SECONDS=15
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
# PADL_STORAGE_BACKEND=supabase
# DATABASE_URL=postgresql://...
# TELEGRAM_WEBHOOK_SECRET_TOKEN=replace-me
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
- при повторе того же `update_id` возвращать `200 OK`, не создавая второй job.

### Trigger retry

`padl-bot-handle-telegram-update` должен быть идемпотентным:

- если `telegram_updates.status = handled`, task возвращает `ignored`;
- если `processing` зависло дольше заданного timeout, task может попробовать заново;
- ошибки Python-команды сохраняются в `telegram_updates.error`.

`padl-bot-scan-once` должен быть идемпотентным через `notified_slots`.

### Недоступность PADL API

Scheduled task обновляет `search_state.last_status` временной ошибкой и завершает run. Следующий cron попробует снова.

### Недоступность Telegram sendMessage

Command task помечает update как `failed` и сохраняет error. Scheduled task помечает конкретные slot notifications как `failed`.

## Тестирование

### Python

- `tests/test_trigger_padl_bot_wrapper.py`: wrapper принимает `scan-once` и `handle-update`.
- `tests/test_trigger_runner.py`: `handle_update` обрабатывает `/start`, `/search`, `/stop`, `/status`, `/venues`, `/now`.
- `tests/test_trigger_runner.py`: повторный `update_id` не обрабатывается второй раз.
- `tests/test_trigger_runner.py`: `scan_once` не дублирует `notified_slots`.
- `tests/test_storage_contract.py`: storage contract проходит для SQLite и fake/Postgres-compatible adapter.
- `tests/test_config.py`: `PADL_STORAGE_BACKEND=supabase` требует `DATABASE_URL`.

### TypeScript

- `src/trigger/padlBotRuntime.test.ts`: env validation и task constants.
- `supabase/functions/telegram-webhook/index.test.ts`: проверка метода, secret header, idempotent insert и Trigger API request.

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
- `padlbot/storage_supabase.py`
- `padlbot/trigger_runner.py`
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
- Edge Function сохраняет update и запускает Trigger task.
- `padl-bot-handle-telegram-update` отвечает на основные Telegram-команды.
- `padl-bot-scan-once` работает по расписанию и отправляет уведомления.
- Supabase Postgres сохраняет active chats, preferences, incoming updates и notified slots.
- Повторные Telegram webhook retries и Trigger retries не создают дублей.
- Локальный `python -m padlbot` продолжает работать через SQLite после `deleteWebhook`.

## Риски

- Команды будут отвечать с небольшой задержкой, потому что Edge Function только ставит задачу, а ответ отправляет Trigger task.
- Если Trigger.dev недоступен, webhook сохранит update, но команда не будет обработана до повторного запуска/ручного recovery.
- Supabase Free tier может быть достаточен для личного бота, но частый cron в Trigger.dev может выйти за бесплатные credits.
- Полный перенос legacy SMS booking state не входит в эту спецификацию.

## Решение

Целевой второй вариант: Supabase является и durable database, и публичным Telegram endpoint, а Trigger.dev остается worker/orchestrator-слоем для Python-кода. Это сохраняет существующую бизнес-логику PADL BOT, убирает зависимость от локального процесса и делает Telegram-команды совместимыми с Trigger Deploy.
