# Спецификация PADL BOT v2.1: Trigger.dev-only self-healing daemon

Дата: 2026-07-02  
Статус: исправленная версия для ревью  
Основана на: `2026-07-02-padl-bot-trigger-only-self-healing-daemon-design.md`  
Цель: запустить PADL BOT в Trigger.dev как долгоживущий самовосстанавливающийся daemon без Supabase и без отдельного публичного webhook/backend, исправив ошибки черновика v2 по Trigger.dev run lifecycle, metadata, Python packaging, env contract и потере состояния.

## Контекст

Текущий бот запускается локально как долгоживущий Python-процесс `python -m padlbot`. Он держит Telegram long polling через `getUpdates`, запускает фоновые `asyncio`-циклы мониторинга и хранит состояние в памяти процесса и локальной SQLite-базе `data/padlbot.db`.

В репозитории уже есть Trigger.dev-каркас:

- `trigger.config.ts` с `runtime: "node"`, `dirs: ["./src/trigger"]` и project id `proj_idvrbofrajznnafltimb`;
- `package.json` с `@trigger.dev/sdk`, но без `@trigger.dev/python`;
- текущий `trigger.config.ts` задает default `maxDuration: 3600`, что не подходит для daemon без task-level override;
- текущий `padlbot.__main__` всегда запускает SMS webhook, поэтому cloud daemon должен иметь отдельный entrypoint;
- текущий `polling_loop` хранит Telegram offset только в памяти и продвигает offset до обработки update.

Предыдущая full-bot спецификация через Supabase решала durable state и webhook ingress схемой:

```text
Telegram webhook -> Supabase Edge Function -> Supabase Postgres -> Trigger.dev task
```

Новая цель обратная: убрать Supabase полностью. Это сознательный обмен надежности данных на простоту и близость к локальной модели процесса.

## Опорные документы

- Trigger.dev tasks overview и `maxDuration`: https://trigger.dev/docs/tasks/overview
- Trigger.dev max duration: https://trigger.dev/docs/runs/max-duration
- Trigger.dev heartbeats: https://trigger.dev/docs/runs/heartbeats
- Trigger.dev run metadata: https://trigger.dev/docs/runs/metadata
- Trigger.dev scheduled tasks: https://trigger.dev/docs/tasks/scheduled
- Trigger.dev runs list API: https://trigger.dev/docs/management/runs/list
- Trigger.dev runs retrieve API: https://trigger.dev/docs/management/runs/retrieve
- Trigger.dev update metadata API: https://trigger.dev/docs/management/runs/update-metadata
- Trigger.dev cancel run API: https://trigger.dev/docs/management/runs/cancel
- Trigger.dev task trigger API: https://trigger.dev/docs/management/tasks/trigger
- Trigger.dev Python extension: https://trigger.dev/docs/config/extensions/pythonExtension
- Telegram Bot API `getUpdates`, `deleteWebhook`: https://core.telegram.org/bots/api#getupdates

## Целевой результат

После `npm run trigger:deploy` в Trigger.dev Production должны существовать две основные task:

```text
padl-bot-daemon
  long-running task
  запускает Python daemon через @trigger.dev/python
  держит Telegram getUpdates polling
  пишет application heartbeat в run metadata через Runs Update Metadata API

padl-bot-ensure-daemon
  scheduled task
  cron каждую минуту
  проверяет active daemon runs
  запускает, отменяет или оставляет daemon по явным правилам
```

Целевая схема:

```text
Trigger.dev schedule padl-bot-ensure-daemon
  -> runs.list(filter taskIdentifier/status)
  -> runs.retrieve(runId) для кандидатов, чтобы получить metadata
  -> classify healthy / starting / stale / old-version / duplicate / unknown
  -> при необходимости runs.cancel + task.trigger

Trigger.dev task padl-bot-daemon
  -> python.runScript("./src/trigger/run_padl_bot.py", ["daemon"], { env })
  -> padlbot.trigger_daemon
  -> Telegram deleteWebhook guard
  -> Telegram getUpdates long polling
  -> existing command handlers в trigger-daemon mode
  -> SearchManager background monitoring loops
  -> Telegram sendMessage
  -> Runs Update Metadata API heartbeat
```

Штатное восстановление означает:

1. Если daemon упал, завис или завершился плановой ротацией, следующий `ensure` запускает новый run.
2. Если filesystem Trigger-run сохранился, SQLite state используется повторно.
3. Если filesystem потерян, daemon восстанавливает минимальный admin-monitoring из env defaults.
4. Не гарантируется восстановление всех пользовательских настроек, дедупликации уведомлений и exactly-once обработки после hard crash.

## Не цели

- Не использовать Supabase Edge Functions, Supabase Postgres, Supabase migrations или Supabase secrets.
- Не добавлять новый внешний durable database в этой версии.
- Не делать отдельный публичный HTTP endpoint для Telegram webhook.
- Не запускать Telegram webhook в Production; целевая модель - long polling.
- Не обещать exactly-once обработку Telegram updates и slot notifications после hard crash.
- Не обещать сохранение всех пользовательских настроек, если Trigger filesystem между runs потерян.
- Не восстанавливать автоматическое удержание слотов и SMS-подтверждение в облаке.
- Не делать пользовательский веб-интерфейс.

## Quality attributes

| Атрибут | Оценка | Комментарий |
| --- | --- | --- |
| Deployability | 4/5 | Один `trigger deploy`, без Supabase. Требуется правильно упаковать Python через `pythonExtension`. |
| Reliability процесса | 3/5 | Supervisor-контур восстанавливает daemon, но зависит от Trigger.dev platform и Management API. |
| Reliability данных | 2/5 | Без durable DB возможны дубли, потеря настроек и потеря дедупликации. Это принято для личного бота. |
| Maintainability | 3/5 | Добавляется небольшой TypeScript supervisor и отдельный Python daemon entrypoint. Границы должны быть явными. |
| Testability | 4/5 | Большая часть supervisor-логики тестируется pure TypeScript/Python unit tests. Полный cancel child-process требует integration test. |
| Security | 3/5 | Нет публичного webhook. `TRIGGER_SECRET_KEY` нужен Python heartbeat, поэтому metadata/logs не должны содержать секреты. |

Вердикт: `Minor improvements` после внесения этой версии. До исправлений v2 имела `Needs restructuring` из-за неверного lifecycle-контракта и завышенных гарантий восстановления.

## Архитектурное решение

ADR: Trigger.dev-only self-healing long-running daemon.

### Context

Пользовательская цель - сохранить модель процесса, близкую к локальному боту: один процесс долго живет, сам получает Telegram updates, сам держит фоновые циклы мониторинга и не требует Supabase. Trigger.dev подходит как managed runner для long-running tasks, но не является прикладной БД. Поэтому reliability данных ниже, чем в Supabase-варианте.

### Options

1. Trigger.dev-only daemon.
   - Оптимизирует простоту, отсутствие Supabase и близость к текущему `python -m padlbot`.
   - Жертвует durable state, exactly-once и надежной дедупликацией между runs.
   - Effort: medium.
   - Reversibility: high, потому что Supabase/Postgres слой не добавляется.

2. Supabase webhook + Postgres + Trigger tasks.
   - Оптимизирует reliable ingestion, durable preferences, dedupe и retries.
   - Жертвует простотой: появляется публичный endpoint, migrations, storage abstraction и recovery-протокол.
   - Effort: medium/high.
   - Reversibility: medium.

3. Scheduled-only Trigger scan-once без Telegram command parity.
   - Оптимизирует стоимость и простоту Trigger tasks.
   - Жертвует интерактивными Telegram-командами в Production.
   - Effort: low.
   - Reversibility: high.

### Decision

Выбрать вариант 1 как v2.1, но явно ограничить обещания:

- daemon self-healing отвечает за восстановление процесса;
- SQLite в Trigger Cloud считается best-effort cache/state, а не источником истины;
- env defaults восстанавливают только минимальный admin-monitoring;
- duplicate notifications и повторная обработка последних Telegram updates являются ожидаемым at-least-once поведением.

Trade-off: платим постоянными Trigger.dev compute credits и слабой надежностью данных, чтобы не вводить Supabase и сохранить long-running bot process.

### Revisit trigger

Пересмотреть архитектуру в сторону durable DB/webhook, если выполняется одно из условий:

- дубли уведомлений или потеря настроек мешают пользоваться ботом чаще 1 раза в неделю;
- средняя недоступность после platform/worker outage превышает 10 минут;
- стоимость long-running Trigger.dev daemon становится неприемлемой для личного бота;
- нужно поддержать больше одного активного пользователя с надежными preferences;
- требуется вернуть cloud booking/SMS state или exactly-once notification semantics.

## Trigger.dev packaging

`package.json`:

- добавить dependency `@trigger.dev/python`;
- добавить script `test:trigger` для TypeScript unit tests;
- добавить script `trigger:dry-run` как `trigger deploy --dry-run`;
- оставить `trigger:deploy`.

`trigger.config.ts`:

```ts
import { defineConfig } from "@trigger.dev/sdk";
import { pythonExtension } from "@trigger.dev/python/extension";

export default defineConfig({
  project: "proj_idvrbofrajznnafltimb",
  runtime: "node",
  logLevel: "log",
  maxDuration: 3600,
  retries: {
    enabledInDev: true,
    default: {
      maxAttempts: 3,
      minTimeoutInMs: 1000,
      maxTimeoutInMs: 10000,
      factor: 2,
      randomize: true,
    },
  },
  dirs: ["./src/trigger"],
  build: {
    extensions: [
      pythonExtension({
        scripts: ["./padlbot/**/*.py", "./src/trigger/**/*.py"],
        requirementsFile: "./requirements.txt",
      }),
    ],
  },
});
```

Default `maxDuration: 3600` может остаться только если `padl-bot-daemon` задает свой task-level `maxDuration`. Иначе daemon будет останавливаться каждый час.

## Trigger.dev task layer

### `padl-bot-daemon`

Создать `src/trigger/padlBotDaemon.ts`.

Task:

```text
id: "padl-bot-daemon"
queue.name: "padl-bot-daemon"
queue.concurrencyLimit: 1
maxDuration: DAEMON_MAX_DURATION_SECONDS, default 86400
retry.maxAttempts: 1
```

`retry.maxAttempts` должен быть `1`. Restart daemon делает только `padl-bot-ensure-daemon`. Если включить retry `2+`, `ensure` обязан учитывать `REATTEMPTING`, иначе возможен второй daemon.

Task не должен detach-ить Python process. TypeScript `run` обязан `await python.runScript(...)`, иначе Trigger run завершится, а orphan process выпадет из supervisor-модели.

Python запускается так:

```ts
const result = await python.runScript(
  "./src/trigger/run_padl_bot.py",
  ["daemon"],
  { env }
);
```

В Python env передаются:

```text
TRIGGER_RUN_ID=<ctx.run.id>
TRIGGER_SECRET_KEY
PADL_TRIGGER_TASK_ID=padl-bot-daemon
PADL_RUNTIME_MODE=trigger-daemon
PADL_DISABLE_SMS_WEBHOOK=1
PADL_DELETE_WEBHOOK_ON_START=1
PADL_HEARTBEAT_SECONDS=30
PADL_DAEMON_GENERATION=<Trigger run version or deploy generation>
PADL_DAEMON_ROTATE_AFTER_SECONDS=82800
```

`TRIGGER_RUN_ID` нужен Python-коду для `PUT /api/v1/runs/{runId}/metadata`. `TRIGGER_SECRET_KEY` нельзя писать в logs, stdout, stderr или metadata.

`maxDuration` и planned rotation:

```text
DAEMON_MAX_DURATION_SECONDS=86400
PADL_DAEMON_ROTATE_AFTER_SECONDS=82800
```

`PADL_DAEMON_ROTATE_AFTER_SECONDS` должен быть минимум на 10 минут меньше `DAEMON_MAX_DURATION_SECONDS`, чтобы planned shutdown успел обновить metadata и закрыть sessions до hard stop.

### `padl-bot-ensure-daemon`

Создать scheduled task в `src/trigger/padlBotDaemon.ts` через `schedules.task`.

```ts
export const ensureDaemon = schedules.task({
  id: "padl-bot-ensure-daemon",
  cron: {
    pattern: "* * * * *",
    timezone: "Europe/Moscow",
    environments: ["PRODUCTION"],
  },
  ttl: "1m",
  queue: {
    name: "padl-bot-ensure-daemon",
    concurrencyLimit: 1,
  },
  run: async (payload, { ctx }) => {
    // supervisor flow
  },
});
```

Declarative schedule должен быть в `cron` на `schedules.task`, чтобы `trigger deploy` синхронизировал расписание. Отдельные поля `timezone` и `environments` вне `cron` не являются целевым контрактом.

### Active statuses

`ensure` ищет daemon runs по `taskIdentifier = "padl-bot-daemon"` и статусам:

```text
PENDING_VERSION
DELAYED
QUEUED
EXECUTING
REATTEMPTING
FROZEN
```

`WAITING` не использовать: этого статуса нет в актуальном Runs API.

Статусы `COMPLETED`, `CANCELED`, `FAILED`, `CRASHED`, `INTERRUPTED`, `SYSTEM_FAILURE` не являются active candidates.

### Metadata retrieval

`runs.list` использовать только для первичного списка кандидатов. Для каждого active candidate `ensure` должен вызвать `runs.retrieve(runId)`, потому что metadata не является надежной частью list-response.

`updatedAt` нельзя использовать как heartbeat fallback. Это техническая метка run, а не application heartbeat.

Если `runs.retrieve` или metadata недоступны:

- если есть `EXECUTING` candidate моложе `PADL_START_GRACE_SECONDS`, классифицировать как `starting`;
- если есть `EXECUTING` candidate старше grace, классифицировать как `unknown`;
- при `unknown` не запускать второй daemon в том же ensure-run, а вернуть summary с warning;
- следующий scheduled run повторит retrieve.

Такой fail-closed подход уменьшает риск двух одновременных `getUpdates`.

### Run classification

Входные поля:

```text
run.id
run.status
run.version
run.startedAt
run.createdAt
run.metadata.heartbeatAt
run.metadata.status
run.metadata.generation
```

Классы:

- `healthy`: `status = EXECUTING`, version совпадает с текущей deployed version, `heartbeatAt` свежее `PADL_HEARTBEAT_STALE_SECONDS`.
- `starting`: `QUEUED`, `DELAYED`, `PENDING_VERSION` или `EXECUTING` без heartbeat, если возраст меньше `PADL_START_GRACE_SECONDS`.
- `stale`: `EXECUTING`, version совпадает, но `heartbeatAt` старше `PADL_HEARTBEAT_CANCEL_AFTER_SECONDS`.
- `stale-warn`: heartbeat старше `PADL_HEARTBEAT_STALE_SECONDS`, но младше cancel threshold.
- `old-version`: run.version не совпадает с current deployment version.
- `duplicate`: лишний active run при наличии более нового `healthy`.
- `unknown`: недостаточно данных, чтобы безопасно принять решение.
- `bad-retry-state`: `REATTEMPTING` при daemon retry policy `maxAttempts: 1`; это считается config drift.
- `frozen`: `FROZEN`; не считать healthy.

`current deployment version` берется из Trigger run version текущего ensure-run. Если SDK context не дает version напрямую, `ensure` должен `runs.retrieve(ctx.run.id)` и взять `version` оттуда.

### Supervisor decisions

Порядок действий:

1. Если `PADL_DAEMON_ENABLED != 1`, не запускать daemon.
2. Если `PADL_DAEMON_ENABLED != 1` и `PADL_DAEMON_STOP_WHEN_DISABLED=1`, отменить active daemon candidates.
3. Если есть ровно один `healthy` текущей версии и нет duplicates, вернуть `{"status":"healthy"}`.
4. Если есть `starting` текущей версии, вернуть `{"status":"starting"}` и не запускать новый daemon.
5. Если есть `stale-warn`, вернуть warning и не отменять.
6. Если есть `stale`, вызвать `runs.cancel(runId)`, затем trigger нового daemon.
7. Если есть `old-version`, отменить старый run и trigger нового daemon текущей версии.
8. Если есть несколько healthy daemon, оставить самый новый по `startedAt`, остальные cancel.
9. Если есть `unknown`, не запускать новый daemon в этом ensure-run.
10. Если daemon candidates отсутствуют, trigger нового daemon.

Trigger нового daemon:

```text
payload:
  reason: missing | stale | old-version | manual-restart
  requestedAt: ISO timestamp
  requestedByRunId: <ensure run id>
  generation: <current version>
options:
  tags: ["padl-bot", "daemon"]
  concurrencyKey: "padl-bot-daemon-production"
  idempotencyKey: "padl-bot-daemon-start-<YYYY-MM-DDTHH:mm>"
  queue.name: "padl-bot-daemon"
  queue.concurrencyLimit: 1
  maxDuration: DAEMON_MAX_DURATION_SECONDS
```

Minute-scoped idempotency key защищает overlapping ensure-runs. Queue concurrency и `concurrencyKey` защищают от штатного параллелизма. `ensure` все равно обязан проверять duplicates, потому что manual trigger или platform race могут создать неожиданные active runs.

## Python daemon runner

Создать:

```text
src/trigger/run_padl_bot.py
padlbot/trigger_daemon.py
```

CLI:

```text
python src/trigger/run_padl_bot.py daemon
python src/trigger/run_padl_bot.py healthcheck
```

`run_padl_bot.py` только добавляет project root в `sys.path`, парсит command и передает управление в `padlbot.trigger_daemon`.

`padlbot.trigger_daemon` не должен вызывать `padlbot.__main__.main()` напрямую, потому что локальный entrypoint стартует SMS webhook и single-instance lock. Cloud daemon должен собирать компоненты сам.

`daemon` делает:

1. Загружает `Config.from_env()`.
2. Валидирует trigger-daemon env.
3. Если `PADL_DELETE_WEBHOOK_ON_START=1`, вызывает Telegram `deleteWebhook(drop_pending_updates=PADL_DROP_PENDING_UPDATES_ON_START)`.
4. Создает `Storage`, `OutdoorApiClient`, `TelegramBot`, `SearchManager`.
5. Не запускает SMS webhook, если `PADL_RUNTIME_MODE=trigger-daemon` или `PADL_DISABLE_SMS_WEBHOOK=1`.
6. Если SQLite содержит active searches, вызывает `resume_active_searches`.
7. Если `AUTO_START_SEARCH=1` и `ADMIN_CHAT_ID` задан, включает admin monitoring с env defaults при пустом storage.
8. Запускает application heartbeat loop.
9. Запускает Telegram polling loop.
10. На `SIGTERM`, `CancelledError` или planned rotation останавливает polling, ждет текущий update, отменяет background search tasks, закрывает aiohttp sessions и пишет final metadata.

## Application heartbeat

Trigger.dev runtime сам отправляет platform heartbeat, чтобы run не считался stalled. Это не заменяет application heartbeat.

Application heartbeat хранится в run metadata и обновляется Python daemon через Runs Update Metadata API:

```json
{
  "kind": "padl-bot-daemon",
  "status": "running",
  "heartbeatAt": "2026-07-02T12:00:00Z",
  "generation": "20240523.1",
  "telegramPolling": "active",
  "activeSearchTasks": 1,
  "lastUpdateId": 123456789,
  "lastLoopError": null,
  "startedAt": "2026-07-02T11:59:00Z"
}
```

Heartbeat update:

```text
PUT https://api.trigger.dev/api/v1/runs/{TRIGGER_RUN_ID}/metadata
Authorization: Bearer TRIGGER_SECRET_KEY
Content-Type: application/json

{ "metadata": { ... } }
```

Правила:

- heartbeat payload не содержит токены, телефоны, email, raw Telegram messages или PADL API responses;
- heartbeat errors не валят daemon сразу;
- при ошибках используется exponential backoff;
- после `PADL_HEARTBEAT_MAX_FAILURES` daemon пишет warning в logs и metadata при следующем успешном update;
- `ensure` не использует `updatedAt` как heartbeat.

Рекомендуемые thresholds:

```text
PADL_HEARTBEAT_SECONDS=30
PADL_HEARTBEAT_MAX_FAILURES=10
PADL_HEARTBEAT_STALE_SECONDS=180
PADL_HEARTBEAT_CANCEL_AFTER_SECONDS=300
PADL_START_GRACE_SECONDS=180
```

## Planned rotation

Чтобы daemon не накапливал утечки памяти и не упирался в `maxDuration`, Python завершает себя после `PADL_DAEMON_ROTATE_AFTER_SECONDS`.

Порядок:

1. Metadata `status = "rotating"`.
2. Остановить прием новых Telegram updates.
3. Дождаться завершения текущей обработки update.
4. Отменить active search tasks.
5. Закрыть sessions.
6. Metadata `status = "exiting", exitReason = "planned-rotation"`.
7. Завершить Python с кодом `0`.
8. TypeScript task завершается successfully.
9. Следующий `ensure` видит отсутствие active daemon и запускает новый.

Zero-gap rotation не является целью v2.1. Допускается окно до следующего cron tick.

## Telegram polling contract

Webhook не используется. На старте daemon должен удалить webhook, если включен `PADL_DELETE_WEBHOOK_ON_START=1`.

Polling:

```text
getUpdates(timeout=30, allowed_updates=["message"], offset=<last confirmed offset>)
```

Offset rules:

- offset продвигается только после успешной обработки update или осознанного ignore;
- offset не продвигается перед `handle_message`;
- `last_update_id` хранится в `RuntimeState`;
- если SQLite доступен, offset сохраняется в таблице `telegram_polling_state`;
- metadata обновляет `lastUpdateId` после обработки batch;
- если offset потерян, daemon полагается на Telegram pending updates.

После crash возможна повторная доставка последнего update. Это ожидаемое at-least-once поведение.

При Telegram conflict из-за второго polling instance daemon должен:

1. записать metadata `telegramPolling = "conflict"`;
2. завершиться non-zero, если конфликт повторяется дольше `PADL_TELEGRAM_CONFLICT_EXIT_SECONDS`;
3. позволить `ensure` оставить один healthy daemon.

Команды в trigger-daemon mode:

- `/start`, `/search`, `/stop`, `/status`, `/venues`, `/now`, `/profile` работают через существующий command handler;
- `/search` запускает долгоживущий `SearchManager.start_search`;
- `/stop` отменяет in-memory search task и пишет inactive state в SQLite;
- `/now` делает синхронную проверку;
- `/code` и `/resend` отвечают текстом, что автоматическое удержание слотов и SMS-подтверждение в облачном режиме отключены.

## State policy без Supabase

Основной storage остается SQLite через `PADL_DB_PATH`. В Trigger Cloud этот файл считается best-effort state, а не durable source of truth.

Целевая политика:

1. Внутри одного daemon run SQLite и memory state используются как обычно.
2. Если filesystem пережил restart, daemon использует `profiles`, `preferences`, `search_state`, `last_bookings`, `notified_slots`, `telegram_polling_state`.
3. Если filesystem потерян, daemon восстанавливает только admin default monitoring из env:
   - `ADMIN_CHAT_ID`;
   - `AUTO_START_SEARCH=1`;
   - `PADL_DEFAULT_VENUE_IDS`;
   - default unbounded search preferences.
4. Пользователь может восстановить настройки командами `/venues`, `/search`, `/profile`.
5. Дубли slot notifications после потери storage допустимы.

SQLite additions:

```text
notified_slots
  chat_id INTEGER NOT NULL
  slot_key TEXT NOT NULL
  first_notified_at TEXT NOT NULL
  PRIMARY KEY(chat_id, slot_key)

telegram_polling_state
  id INTEGER PRIMARY KEY CHECK (id = 1)
  last_update_id INTEGER
  updated_at TEXT NOT NULL
```

`notified_slots` уменьшает дубли при мягком restart, но не является строгой гарантией в Trigger Cloud.

## Config/env contract

Добавить в `Config` поля:

```text
runtime_mode
disable_sms_webhook
daemon_enabled
daemon_stop_when_disabled
delete_webhook_on_start
drop_pending_updates_on_start
default_venue_ids
heartbeat_seconds
heartbeat_stale_seconds
heartbeat_cancel_after_seconds
heartbeat_max_failures
start_grace_seconds
daemon_rotate_after_seconds
telegram_conflict_exit_seconds
```

Обязательные Trigger.dev Production env:

```text
TELEGRAM_BOT_TOKEN
TRIGGER_SECRET_KEY
PADL_DAEMON_ENABLED=1
ADMIN_CHAT_ID
AUTO_START_SEARCH=1
PADL_DEFAULT_VENUE_IDS=12,14,15
PADL_SITE_BASE_URL=https://api.outdoor.sport.mos.ru
REQUEST_TIMEOUT_SECONDS=15
PADL_RUNTIME_MODE=trigger-daemon
PADL_DISABLE_SMS_WEBHOOK=1
```

Рекомендуемые:

```text
PADL_DB_PATH=data/padlbot.db
PADL_DELETE_WEBHOOK_ON_START=1
PADL_DROP_PENDING_UPDATES_ON_START=0
PADL_HEARTBEAT_SECONDS=30
PADL_HEARTBEAT_MAX_FAILURES=10
PADL_HEARTBEAT_STALE_SECONDS=180
PADL_HEARTBEAT_CANCEL_AFTER_SECONDS=300
PADL_START_GRACE_SECONDS=180
PADL_DAEMON_ROTATE_AFTER_SECONDS=82800
DAEMON_MAX_DURATION_SECONDS=86400
PADL_DAEMON_STOP_WHEN_DISABLED=0
PADL_TELEGRAM_CONFLICT_EXIT_SECONDS=120
```

Validation:

- `TELEGRAM_BOT_TOKEN` обязателен всегда.
- `TRIGGER_SECRET_KEY` обязателен при `PADL_RUNTIME_MODE=trigger-daemon`.
- `ADMIN_CHAT_ID` обязателен, если `AUTO_START_SEARCH=1`.
- `PADL_DEFAULT_VENUE_IDS` обязателен, если `AUTO_START_SEARCH=1` и storage пустой.
- `PADL_DAEMON_ROTATE_AFTER_SECONDS < DAEMON_MAX_DURATION_SECONDS - 600`.
- `PADL_HEARTBEAT_STALE_SECONDS > PADL_HEARTBEAT_SECONDS`.
- `PADL_HEARTBEAT_CANCEL_AFTER_SECONDS > PADL_HEARTBEAT_STALE_SECONDS`.

## Self-healing scenarios

### Daemon отсутствует после deploy

1. `padl-bot-ensure-daemon` запускается по declarative schedule.
2. `runs.list` не находит active candidates.
3. `ensure` trigger-ит daemon с reason `missing`.
4. Daemon стартует, удаляет webhook при необходимости, начинает polling.

### Daemon упал

1. `padl-bot-daemon` получает terminal status `FAILED`, `CRASHED`, `INTERRUPTED` или `SYSTEM_FAILURE`.
2. Следующий `ensure` не видит active candidates.
3. `ensure` запускает новый daemon.
4. Возможна повторная доставка последнего Telegram update.

### Daemon завис

1. Daemon перестает обновлять application heartbeat.
2. `ensure` делает `runs.retrieve` и видит stale heartbeat.
3. До `PADL_HEARTBEAT_CANCEL_AFTER_SECONDS` только warning.
4. После cancel threshold `ensure` вызывает `runs.cancel(runId)`.
5. После cancel trigger-ит новый daemon.

### Management API временно недоступен

1. Daemon продолжает Telegram polling.
2. Heartbeat update может падать и retry-иться.
3. `ensure` может fail-нуться на list/retrieve/cancel/trigger.
4. Следующий scheduled run повторит попытку.
5. Если daemon жив, пользовательские команды продолжают работать.

### Metadata retrieve недоступен, но list видит EXECUTING

1. `ensure` классифицирует run как `unknown`.
2. Новый daemon не запускается в этом ensure-run.
3. Summary содержит warning.
4. Следующий cron повторяет retrieve.

Это осознанный выбор: лучше кратковременно пропустить restart, чем создать второй Telegram polling process.

### Новый deploy

1. Новый deploy публикует новую version tasks.
2. Scheduled tasks старых deployments больше не запускаются.
3. `ensure` новой версии видит daemon старой `run.version`.
4. `ensure` отменяет old-version run и запускает daemon новой версии.
5. Допускается короткое окно без polling.

### Потеря локального файла состояния

1. Новый daemon стартует с пустым SQLite.
2. `AUTO_START_SEARCH=1` включает мониторинг для `ADMIN_CHAT_ID`.
3. Default venues берутся из `PADL_DEFAULT_VENUE_IDS`.
4. Пользователь может уточнить настройки командами.
5. Возможны дубли уведомлений о слотах.
6. Настройки других пользователей не восстанавливаются автоматически.

### Trigger.dev platform outage

Автоматическое восстановление невозможно, пока сама платформа не запускает tasks. После восстановления scheduled `ensure` снова запустится и поднимет daemon. Telegram pending updates могут быть доставлены повторно или частично, в зависимости от поведения Telegram и длительности outage.

## Изменения в файлах

Создать:

- `src/trigger/padlBotDaemon.ts`
- `src/trigger/padlBotDaemonRuntime.ts`
- `src/trigger/padlBotDaemonRuntime.test.ts`
- `src/trigger/run_padl_bot.py`
- `padlbot/trigger_daemon.py`
- `tests/test_trigger_daemon.py`
- `tests/test_trigger_daemon_wrapper.py`

Изменить:

- `package.json`
- `package-lock.json`
- `trigger.config.ts`
- `.env.example`
- `requirements.txt`, если heartbeat API будет использовать новый HTTP client
- `padlbot/config.py`
- `padlbot/telegram_polling.py`
- `padlbot/service.py`
- `padlbot/storage.py`
- `README.md`
- `README_RU.md`

Не создавать:

- `supabase/functions/telegram-webhook/index.ts`
- `supabase/migrations/*`
- `padlbot/storage_postgres.py`

Удалить, если больше не нужен:

- `src/trigger/example.ts`

## Тестирование

### TypeScript unit tests

- env validation для daemon/ensure.
- `classifyDaemonRun` не использует `WAITING`.
- `classifyDaemonRun` отличает `healthy`, `starting`, `stale-warn`, `stale`, `old-version`, `duplicate`, `unknown`, `bad-retry-state`, `frozen`.
- `runs.list` result без metadata приводит к `runs.retrieve`.
- `updatedAt` не используется как heartbeat fallback.
- `unknown` не trigger-ит новый daemon.
- no active run -> trigger daemon.
- healthy run -> no-op.
- starting run -> no-op.
- stale run -> cancel + trigger.
- old-version run -> cancel + trigger.
- multiple healthy runs -> cancel duplicates.
- `PADL_DAEMON_ENABLED=0` -> no start.
- `PADL_DAEMON_ENABLED=0` и `PADL_DAEMON_STOP_WHEN_DISABLED=1` -> cancel active daemon.
- daemon task имеет task-level `maxDuration > PADL_DAEMON_ROTATE_AFTER_SECONDS`.
- daemon task имеет `retry.maxAttempts = 1`.
- scheduled task использует `schedules.task` и `cron: { pattern, timezone, environments }`.

### Python unit tests

- wrapper принимает `daemon` и передает управление `padlbot.trigger_daemon`.
- trigger daemon startup не вызывает `start_sms_webhook`.
- `PADL_DISABLE_SMS_WEBHOOK=1` отключает SMS webhook.
- `/code` и `/resend` в trigger-daemon mode возвращают cloud-disabled message.
- `Config.from_env()` парсит `PADL_DEFAULT_VENUE_IDS` и heartbeat env.
- `AUTO_START_SEARCH=1` без `ADMIN_CHAT_ID` падает config validation.
- empty SQLite + env defaults запускает admin monitoring.
- heartbeat payload не содержит секретов и персональных данных.
- heartbeat failure не валит polling loop.
- planned rotation завершает daemon с кодом `0`.
- SIGTERM закрывает aiohttp sessions и отменяет background tasks.
- Telegram offset продвигается только после успешной обработки update.
- Telegram offset сохраняется в SQLite, если storage доступен.
- повторный `/search` безопасен.
- `notified_slots` suppresses duplicate slot notifications при мягком restart.

### Integration checks

```powershell
python -m pytest
npm run test:trigger
npm run trigger:dry-run
npm run trigger:deploy
```

После deploy:

1. `padl-bot-ensure-daemon` появляется в Trigger Dashboard как scheduled task.
2. Через минуту после deploy появляется `EXECUTING` run `padl-bot-daemon`.
3. `runs.retrieve` показывает metadata с `heartbeatAt`.
4. `/start` в Telegram получает ответ.
5. `/search` запускает мониторинг.
6. `/status` показывает активное состояние.
7. Искусственная отмена daemon приводит к запуску нового run следующим `ensure`.
8. Искусственно устаревший heartbeat приводит к cancel + restart только после cancel threshold.
9. Временная недоступность metadata retrieve не создает второй daemon.
10. При `PADL_DAEMON_ENABLED=0` daemon не запускается заново.
11. При `PADL_DAEMON_ENABLED=0` и `PADL_DAEMON_STOP_WHEN_DISABLED=1` активный daemon отменяется.
12. Два ручных daemon starts не приводят к двум долгоживущим healthy polling process.

## Fitness functions

- `padlBotDaemonRuntime.test.ts` доказывает, что `WAITING` отсутствует из classification input.
- `padlBotDaemonRuntime.test.ts` доказывает fail-closed поведение при missing metadata.
- `padlBotDaemonRuntime.test.ts` доказывает, что stale определяется только по `metadata.heartbeatAt`.
- `padlBotDaemonRuntime.test.ts` доказывает, что daemon retry policy равна `maxAttempts: 1`.
- `tests/test_trigger_daemon.py` доказывает, что trigger-daemon mode не запускает SMS webhook.
- `tests/test_telegram_polling.py` доказывает продвижение offset после обработки update.
- `tests/test_storage.py` доказывает сохранение `telegram_polling_state` и `notified_slots`.
- `npm run trigger:dry-run` доказывает, что Python scripts и `requirements.txt` входят в Trigger build.
- Manual deploy check доказывает, что `runs.retrieve` видит metadata heartbeat и `ensure` не запускает duplicate daemon.

## Критерии готовности

- Supabase полностью отсутствует из целевой архитектуры v2.1.
- `npm run trigger:deploy` публикует `padl-bot-daemon` и `padl-bot-ensure-daemon`.
- `trigger.config.ts` подключает `pythonExtension` с `padlbot/**/*.py`, `src/trigger/**/*.py` и `requirements.txt`.
- `padl-bot-daemon` имеет task-level `maxDuration`, который больше planned rotation.
- `padl-bot-daemon` имеет `retry.maxAttempts = 1`.
- `padl-bot-ensure-daemon` использует declarative `schedules.task` cron.
- `ensure` не использует несуществующий статус `WAITING`.
- `ensure` получает metadata через `runs.retrieve`, а не из `runs.list`.
- `ensure` не использует `updatedAt` как heartbeat.
- После deploy daemon стартует автоматически без ручного trigger.
- Daemon держит Telegram long polling и отвечает на основные команды.
- `/search` в Trigger daemon запускает долгоживущий мониторинг, как локальная версия.
- `/code` и `/resend` в Trigger daemon не пытаются выполнять cloud SMS booking.
- Heartbeat виден в Trigger run metadata и обновляется регулярно.
- `ensure` сам запускает daemon, если его нет.
- `ensure` сам отменяет stale daemon и запускает новый после cancel threshold.
- `ensure` не запускает второй daemon, если есть healthy, starting или unknown active candidate.
- `PADL_DAEMON_ENABLED=0` работает как kill switch.
- При hard crash система возвращает процесс и admin-monitoring из env defaults.
- README описывает штатный self-healing flow, ограничения state recovery и manual emergency flow.

## Риски

- Long-running daemon может потреблять Trigger.dev credits постоянно.
- Без внешней durable DB нельзя гарантировать exactly-once после hard crash.
- Потеря filesystem между runs может сбросить preferences, notified slots и polling offset.
- Heartbeat через Trigger Management API добавляет зависимость от API для observability.
- `ensure` может временно оставить зависший daemon, если metadata недоступна; это осознанный fail-closed trade-off против duplicate polling.
- Telegram long polling конфликтует с webhook и локальным `python -m padlbot`; документация должна предупреждать не держать локальный polling одновременно с Trigger daemon.

## Migration path

1. Добавить `@trigger.dev/python` и `pythonExtension`.
2. Добавить trigger runtime helpers и unit tests для classification.
3. Расширить `Config` новым env contract.
4. Добавить `trigger_daemon.py`, который не использует локальный `__main__`.
5. Добавить heartbeat update API client.
6. Исправить Telegram polling offset ordering.
7. Добавить SQLite best-effort tables.
8. Добавить `padl-bot-daemon` и `padl-bot-ensure-daemon`.
9. Запустить unit tests и dry-run.
10. Deploy в Production.
11. Проверить Dashboard, Telegram commands, cancel/restart и kill switch.

## Self-review

- Плейсхолдеров нет.
- Старый `WAITING` удален; актуальные run statuses зафиксированы.
- Metadata больше не берется из `runs.list`; нужен `runs.retrieve`.
- `updatedAt` не используется как heartbeat.
- Обещания hard crash recovery ограничены admin defaults, а не полным восстановлением всех пользователей.
- SMS-disable переведен из пожелания в env/config/test contract.
- Python packaging через `pythonExtension` включен в обязательный scope.
- Planned rotation и cancel child-process требуют integration verification.
