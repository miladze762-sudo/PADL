# Спецификация PADL BOT v2: Trigger.dev-only self-healing daemon

Дата: 2026-07-02  
Статус: черновик для ревью  
Цель: отказаться от Supabase и запустить PADL BOT в Trigger.dev как долгоживущий самовосстанавливающийся процесс, близкий к текущему локальному `python -m padlbot`, но без ручного восстановления после обычных сбоев.

## Контекст

Текущий бот запускается локально как долгоживущий Python-процесс. Он держит Telegram long polling через `getUpdates`, запускает фоновые `asyncio`-циклы мониторинга и хранит оперативное состояние в памяти процесса и локальной SQLite-базе `data/padlbot.db`.

Предыдущая full-bot спецификация предлагала заменить локальный процесс схемой:

```text
Telegram webhook -> Supabase Edge Function -> Supabase Postgres -> Trigger.dev task
```

Новая цель обратная: убрать Supabase полностью и не добавлять отдельный публичный webhook/backend. Trigger.dev должен стать местом, где живет сам bot process. Это сознательный отход от short-lived task модели в пользу long-running task: процесс должен работать долго, сам подниматься после падения и продолжать Telegram polling.

Официальные опорные документы:

- Trigger.dev tasks overview и `maxDuration`: https://trigger.dev/docs/tasks/overview
- Trigger.dev max duration: https://trigger.dev/docs/runs/max-duration
- Trigger.dev scheduled tasks: https://trigger.dev/docs/tasks/scheduled
- Trigger.dev run metadata: https://trigger.dev/docs/runs/metadata
- Trigger.dev runs list API: https://trigger.dev/docs/management/runs/list
- Trigger.dev cancel run API: https://trigger.dev/docs/management/runs/cancel
- Trigger.dev task trigger API: https://trigger.dev/docs/management/tasks/trigger
- Trigger.dev Python extension: https://trigger.dev/docs/config/extensions/pythonExtension
- Telegram Bot API `getUpdates`, `deleteWebhook`: https://core.telegram.org/bots/api#getupdates

## Целевой результат

После `npm run trigger:deploy` в Trigger.dev Production должны существовать два основных task:

```text
padl-bot-daemon
  long-running background task, запускается ensure-контуром или аварийно вручную
  запускает Python daemon и держит Telegram getUpdates polling

padl-bot-ensure-daemon
  scheduled task, cron * * * * *, timezone Europe/Moscow
  проверяет, что daemon жив, и сам запускает/перезапускает его
```

Целевая схема:

```text
Trigger.dev schedule padl-bot-ensure-daemon
  -> list active padl-bot-daemon runs
  -> если daemon отсутствует, завис или устарел: cancel/trigger

Trigger.dev long-running task padl-bot-daemon
  -> Python daemon runner
  -> Telegram deleteWebhook guard
  -> Telegram getUpdates long polling
  -> existing command handlers
  -> SearchManager background monitoring loops
  -> Telegram sendMessage
  -> Trigger run metadata heartbeat
```

Штатное восстановление должно быть автоматическим. Ручные действия остаются только для аварийной диагностики, обслуживания env или принудительной остановки.

## Не цели

- Не использовать Supabase Edge Functions, Supabase Postgres, Supabase migrations или Supabase secrets.
- Не делать отдельный публичный HTTP endpoint для Telegram webhook.
- Не запускать Telegram webhook в Production; целевая модель - long polling.
- Не добавлять новый внешний durable database в этой версии.
- Не обещать exactly-once обработку Telegram updates и уведомлений после hard crash.
- Не восстанавливать автоматическое удержание слотов и SMS-подтверждение в облаке.
- Не делать пользовательский веб-интерфейс.

## Ключевое архитектурное решение

ADR: Trigger.dev-only self-healing long-running daemon.

### Почему так

Пользовательская цель - сохранить модель процесса, близкую к оригиналу: один бот живет долго, сам получает Telegram updates, сам держит фоновые циклы мониторинга и не требует Supabase. Trigger.dev подходит как managed runner для long-running задач, но не является прикладной БД. Поэтому надежность строится не на внешнем storage, а на supervisor-контуре:

1. `padl-bot-daemon` выполняет работу.
2. `padl-bot-ensure-daemon` регулярно проверяет daemon и возвращает систему в рабочее состояние.
3. Heartbeat пишется в Trigger run metadata.
4. Запуск daemon защищен queue concurrency и management checks.
5. После потери памяти процесса система сама стартует заново из env defaults.

### Компромисс

Без внешней durable БД после жесткого сбоя возможны:

- повторная обработка последних Telegram updates;
- повторный ответ на команду `/now` или `/status`;
- повторное уведомление о слоте, если `notified_slots` был только в памяти или потерян вместе с локальным файлом;
- потеря пользовательских настроек, если filesystem Trigger-run не пережил restart.

Это принимается для личного бота. Предпочтение: лучше автоматически вернуться к работе и иногда продублировать сообщение, чем остановиться до ручного вмешательства.

## Trigger.dev task layer

### `padl-bot-daemon`

Создать `src/trigger/padlBotDaemon.ts` с task:

```text
id: "padl-bot-daemon"
queue.name: "padl-bot-daemon"
queue.concurrencyLimit: 1
maxDuration: DAEMON_MAX_DURATION_SECONDS
retry.maxAttempts: 1 или 2
```

Task запускает Python через `@trigger.dev/python`:

```text
src/trigger/run_padl_bot.py daemon
```

В Python env передаются:

```text
TRIGGER_RUN_ID
TRIGGER_SECRET_KEY
PADL_TRIGGER_TASK_ID=padl-bot-daemon
PADL_RUNTIME_MODE=trigger-daemon
PADL_DISABLE_SMS_WEBHOOK=1
PADL_HEARTBEAT_SECONDS=30
PADL_DAEMON_GENERATION=<iso timestamp or run id>
```

`TRIGGER_RUN_ID` нужен Python-коду, чтобы обновлять run metadata напрямую через Trigger.dev Management API. TypeScript wrapper не должен ждать завершения Python-процесса, чтобы отправить heartbeat: heartbeat делает сам Python daemon.

`maxDuration` должен быть больше плановой ротации. Например:

```text
DAEMON_MAX_DURATION_SECONDS=86400
PADL_DAEMON_ROTATE_AFTER_SECONDS=82800
```

Если Trigger config требует default `maxDuration`, он не должен оставаться `3600` для daemon-режима, иначе бот будет перезапускаться каждый час. Рекомендуется задать отдельный `maxDuration` на daemon task или поднять project default и ограничивать короткие tasks явно.

### `padl-bot-ensure-daemon`

Создать scheduled task:

```text
id: "padl-bot-ensure-daemon"
cron: "* * * * *"
timezone: "Europe/Moscow"
environments: ["PRODUCTION"]
queue.concurrencyLimit: 1
ttl: "1m"
```

Ответственности:

1. Если `PADL_DAEMON_ENABLED != 1`, не запускать daemon. В режиме `PADL_DAEMON_ENABLED=0` task может отменить активный daemon только если `PADL_DAEMON_STOP_WHEN_DISABLED=1`.
2. Получить список runs `padl-bot-daemon` со статусами `QUEUED`, `EXECUTING`, `WAITING`, `DELAYED`.
3. Получить metadata активных runs или использовать `updatedAt`, если metadata недоступна.
4. Классифицировать каждый run:
   - `healthy`: статус исполняется, heartbeat свежее `PADL_HEARTBEAT_STALE_SECONDS`;
   - `stale`: run исполняется, но heartbeat старый;
   - `old-version`: metadata/version не совпадает с текущим deploy generation;
   - `duplicate`: лишний run при наличии более нового healthy run;
   - `unknown`: management API не дал достаточно данных.
5. Если есть ровно один healthy run текущей версии, вернуть summary `{"status":"healthy"}`.
6. Если daemon отсутствует, trigger `padl-bot-daemon`.
7. Если daemon stale, cancel stale run и trigger новый.
8. Если runs несколько, сохранить самый новый healthy run, остальные cancel.
9. Если run старой версии после deploy, cancel его и trigger новый run текущей версии.

Запуск daemon выполняется через SDK или Tasks API с защитой от дублей:

```text
taskIdentifier: padl-bot-daemon
payload: { reason, requestedAt, generation }
options:
  tags: ["padl-bot", "daemon"]
  concurrencyKey: "padl-bot-daemon-production"
  idempotencyKey: "padl-bot-daemon-start-<YYYY-MM-DDTHH:mm>"
  queue.name: "padl-bot-daemon"
  queue.concurrencyLimit: 1
```

Idempotency key ограничен минутой, чтобы два overlapping ensure-run не создали два запуска, но следующая минута могла восстановить daemon, если предыдущий start не удался.

### Manual management tasks

Добавить вспомогательные task:

```text
padl-bot-daemon-health
padl-bot-restart-daemon
padl-bot-stop-daemon
```

Они не являются обязательным путем восстановления, но нужны для диагностики:

- `health` показывает active run id, статус, последнюю heartbeat, возраст daemon, generation, последние ошибки.
- `restart` отменяет текущий daemon и запускает новый через тот же helper, что `ensure`.
- `stop` отменяет daemon. Для длительной остановки нужно также поставить `PADL_DAEMON_ENABLED=0`, иначе следующий `ensure` снова запустит процесс.

## Python daemon runner

Создать или расширить:

```text
src/trigger/run_padl_bot.py
padlbot/trigger_daemon.py
```

CLI:

```text
python src/trigger/run_padl_bot.py daemon
python src/trigger/run_padl_bot.py healthcheck
```

`daemon` делает:

1. Загружает `Config.from_env()`.
2. Валидирует обязательные env.
3. Если `PADL_DELETE_WEBHOOK_ON_START=1`, вызывает Telegram `deleteWebhook`, чтобы `getUpdates` не конфликтовал с webhook.
4. Создает `TelegramBot`, `OutdoorApiClient`, `Storage`, `SearchManager`.
5. Если `AUTO_START_SEARCH=1` и `ADMIN_CHAT_ID` заданы, включает мониторинг для admin chat.
6. Если storage умеет хранить active searches, вызывает `resume_active_searches`.
7. Запускает Telegram `polling_loop`.
8. Запускает heartbeat loop.
9. Корректно завершает сессии и фоновые tasks при `CancelledError`, `SIGTERM` или planned rotation.

### Heartbeat

Python daemon каждые `PADL_HEARTBEAT_SECONDS` обновляет Trigger run metadata:

```json
{
  "kind": "padl-bot-daemon",
  "status": "running",
  "heartbeatAt": "2026-07-02T12:00:00Z",
  "generation": "2026-07-02T11:59:00Z",
  "telegramPolling": "active",
  "activeSearchTasks": 1,
  "lastUpdateId": 123456789,
  "lastLoopError": null,
  "startedAt": "2026-07-02T11:59:00Z"
}
```

Heartbeat errors не должны валить daemon сразу. Если Trigger Management API временно недоступен, daemon продолжает polling и повторяет heartbeat с backoff. После `PADL_HEARTBEAT_MAX_FAILURES` daemon пишет warning в logs, но не прекращает работу сам: иначе ошибка observability превратится в outage.

`padl-bot-ensure-daemon` считает run stale только после запаса:

```text
PADL_HEARTBEAT_SECONDS=30
PADL_HEARTBEAT_MAX_FAILURES=10
PADL_HEARTBEAT_STALE_SECONDS=180
PADL_HEARTBEAT_CANCEL_AFTER_SECONDS=300
```

Так здоровый daemon не будет отменен из-за одного пропущенного metadata update.

### Planned rotation

Чтобы long-running process не накапливал утечки памяти и не упирался в `maxDuration`, daemon завершает себя штатно после `PADL_DAEMON_ROTATE_AFTER_SECONDS`.

Порядок:

1. Metadata `status = "rotating"`.
2. Остановить polling loop.
3. Дождаться завершения текущей обработки update.
4. Отменить search tasks.
5. Закрыть HTTP sessions.
6. Завершить run с кодом `0`.
7. Следующий `padl-bot-ensure-daemon` увидит отсутствие daemon и запустит новый.

Это дает регулярное самовосстановление даже без аварии.

## Telegram polling и обработка команд

Production в Trigger-only v2 использует Telegram long polling:

```text
getUpdates(timeout=30, allowed_updates=["message"])
```

Webhook не используется. На старте daemon должен уметь удалить webhook через `deleteWebhook`, если включен `PADL_DELETE_WEBHOOK_ON_START=1`.

Команды `/start`, `/search`, `/stop`, `/status`, `/venues`, `/now`, `/profile` работают через существующий `padlbot.telegram_polling.handle_message`. Команды `/code` и `/resend` в Trigger daemon должны отвечать понятным текстом, что автоматическое удержание и SMS-подтверждение в облачном режиме отключены, если SMS webhook недоступен.

Для Trigger daemon нужно добавить режим сервисов:

```text
PADL_RUNTIME_MODE=trigger-daemon
```

В этом режиме:

- SMS webhook не стартует;
- `/search` запускает обычный долгоживущий `SearchManager.start_search`, как локально;
- `/stop` отменяет in-memory search task;
- `/now` делает синхронную проверку;
- active search для admin может включаться автоматически через env.

## Состояние без Supabase

Основной storage остается SQLite через `PADL_DB_PATH`. В Trigger Cloud этот файл не считается надежным меж-run источником истины.

Целевая политика:

1. Внутри одного daemon run SQLite и memory state используются как обычно.
2. Если filesystem пережил restart, бот использует сохраненные `profiles`, `preferences`, `search_state`, `last_bookings`.
3. Если filesystem не пережил restart, daemon сам поднимает минимальную рабочую конфигурацию из env:
   - `ADMIN_CHAT_ID`;
   - `AUTO_START_SEARCH=1`;
   - `PADL_DEFAULT_VENUE_IDS`;
   - default unbounded search preferences.
4. Пользователь может восстановить настройки командами `/venues`, `/search`, `/profile`.

Дополнительно в SQLite можно добавить таблицу `notified_slots`, чтобы уменьшить дубли при мягком restart, но спецификация не должна считать это строгой гарантией в Trigger Cloud.

### Telegram update offset

Текущий `polling_loop` хранит offset в памяти. Для v2 нужно улучшить поведение:

- хранить `last_update_id` в `RuntimeState`;
- обновлять run metadata после обработки updates;
- если SQLite доступен, сохранять `telegram_polling_offset`;
- после restart использовать сохраненный offset, если он есть;
- если offset потерян, полагаться на Telegram pending updates.

Offset можно продвигать только после обработки update. Поэтому после crash возможна повторная доставка последнего update. Это ожидаемое at-least-once поведение.

Команды должны быть идемпотентны:

- `/search`: если мониторинг уже запущен, отвечает "Мониторинг уже запущен.";
- `/stop`: повторный вызов безопасен;
- `/venues`: повторное сохранение тех же площадок безопасно;
- `/profile`: повторное сохранение безопасно;
- `/status`: безопасно;
- `/now`: может повторно отправить актуальный список, это допустимо.

## Self-healing сценарии

### Daemon отсутствует после deploy

1. `padl-bot-ensure-daemon` запускается по cron.
2. Не находит active `padl-bot-daemon`.
3. Trigger-ит daemon с reason `missing`.
4. Daemon стартует, удаляет webhook при необходимости, начинает polling.

Ручной запуск после deploy не нужен.

### Python daemon упал

1. `padl-bot-daemon` завершается failed.
2. Следующий `padl-bot-ensure-daemon` не видит executing daemon.
3. Запускает новый daemon.
4. Telegram может повторить последние updates, если offset не был подтвержден.

### Daemon завис

1. Daemon перестает обновлять metadata.
2. `ensure` видит stale heartbeat.
3. Если stale старше `PADL_HEARTBEAT_CANCEL_AFTER_SECONDS`, `ensure` вызывает `runs.cancel(runId)`.
4. После cancel запускает новый daemon.

### Два daemon одновременно

1. Queue concurrency и concurrency key должны не допустить штатный параллелизм.
2. Если из-за race или manual start появились два executing run, `ensure` оставляет самый новый healthy run.
3. Остальные active runs отменяются.

### Новый deploy

1. Новый deploy публикует новую версию tasks.
2. `ensure` текущей версии видит daemon старой generation/version.
3. Отменяет старый run и запускает новый.
4. Если нужно zero-gap обновление, это не цель v2; допускается короткое окно без polling.

### Trigger.dev Management API временно недоступен

1. Daemon продолжает polling, даже если heartbeat не обновился.
2. `ensure` может fail-нуться из-за невозможности list/cancel/trigger.
3. Следующий scheduled run повторит попытку.
4. Если daemon жив, пользовательские команды продолжают работать.

### Trigger.dev worker/platform outage

Автоматическое восстановление невозможно, пока сама платформа не запускает tasks. После восстановления Trigger.dev scheduled `ensure` снова запустится и поднимет daemon. Telegram pending updates могут быть доставлены повторно или частично, в зависимости от поведения Telegram и длительности outage.

### Потеря локального файла состояния

1. Новый daemon стартует с пустым storage.
2. `AUTO_START_SEARCH=1` включает мониторинг для `ADMIN_CHAT_ID`.
3. Default venues берутся из `PADL_DEFAULT_VENUE_IDS`.
4. Пользователь может уточнить настройки командами.
5. Возможны дубли уведомлений о слотах, которые были отправлены до потери storage.

## Env contract

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
PADL_HEARTBEAT_SECONDS=30
PADL_HEARTBEAT_STALE_SECONDS=180
PADL_HEARTBEAT_CANCEL_AFTER_SECONDS=300
PADL_DAEMON_ROTATE_AFTER_SECONDS=82800
DAEMON_MAX_DURATION_SECONDS=86400
PADL_DAEMON_STOP_WHEN_DISABLED=0
```

Опциональные аварийные переключатели:

```text
PADL_DAEMON_ENABLED=0
PADL_DAEMON_STOP_WHEN_DISABLED=1
PADL_DROP_PENDING_UPDATES_ON_START=0
```

`PADL_DROP_PENDING_UPDATES_ON_START=1` использовать только вручную при аварийном завале старых Telegram updates. По умолчанию pending updates не сбрасываются, чтобы не терять команды.

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
- `requirements.txt`, если Python heartbeat будет использовать дополнительный HTTP-клиент вне уже имеющегося `aiohttp`
- `padlbot/config.py`
- `padlbot/telegram_polling.py`
- `padlbot/service.py`
- `padlbot/storage.py`, если будет сохраняться polling offset или `notified_slots`
- `README.md`
- `README_RU.md`

В `package.json` добавить:

- зависимость `@trigger.dev/python`;
- script `test:trigger` для TypeScript unit tests.

Удалить:

- `src/trigger/example.ts`

Не создавать:

- `supabase/functions/telegram-webhook/index.ts`
- `supabase/migrations/*`
- `padlbot/storage_postgres.py`

## Тестирование

### TypeScript

- `padlBotDaemonRuntime.test.ts`: env validation для daemon/ensure.
- `padlBotDaemonRuntime.test.ts`: `classifyDaemonRun` отличает healthy, stale, old-version, duplicate.
- `padlBotDaemonRuntime.test.ts`: no active run -> trigger daemon.
- `padlBotDaemonRuntime.test.ts`: healthy run -> no-op.
- `padlBotDaemonRuntime.test.ts`: stale run -> cancel + trigger.
- `padlBotDaemonRuntime.test.ts`: multiple runs -> cancel duplicates.
- `padlBotDaemonRuntime.test.ts`: `PADL_DAEMON_ENABLED=0` -> no start.

### Python

- `tests/test_trigger_daemon_wrapper.py`: wrapper принимает `daemon` и передает управление `padlbot.trigger_daemon`.
- `tests/test_trigger_daemon.py`: daemon startup включает `AUTO_START_SEARCH` для `ADMIN_CHAT_ID`.
- `tests/test_trigger_daemon.py`: heartbeat payload не содержит секретов.
- `tests/test_trigger_daemon.py`: heartbeat failure не валит polling loop.
- `tests/test_trigger_daemon.py`: planned rotation завершает daemon с кодом `0`.
- `tests/test_telegram_polling.py`: offset продвигается только после обработки update.
- `tests/test_telegram_polling.py`: повторный `/search` безопасен.

### Интеграционные проверки

```powershell
python -m pytest
npm run test:trigger
npm run trigger:dry-run
npm run trigger:deploy
```

После deploy:

1. `padl-bot-ensure-daemon` появляется в Trigger Dashboard как scheduled task.
2. Через минуту после deploy появляется executing run `padl-bot-daemon`.
3. Metadata daemon обновляет `heartbeatAt`.
4. `/start` в Telegram получает ответ.
5. `/search` запускает мониторинг.
6. `/status` показывает активное состояние.
7. Искусственная отмена daemon приводит к автоматическому запуску нового run следующим `ensure`.
8. Искусственно устаревший heartbeat приводит к cancel + restart.
9. При `PADL_DAEMON_ENABLED=0` daemon не запускается заново.

## Критерии готовности

- Supabase полностью отсутствует из целевой архитектуры v2.
- `npm run trigger:deploy` публикует `padl-bot-daemon` и `padl-bot-ensure-daemon`.
- После deploy daemon стартует автоматически без ручного trigger.
- Daemon держит Telegram long polling и отвечает на основные команды.
- `/search` в Trigger daemon запускает долгоживущий мониторинг, как локальная версия.
- Heartbeat виден в Trigger run metadata и обновляется регулярно.
- `ensure` сам запускает daemon, если его нет.
- `ensure` сам отменяет stale daemon и запускает новый.
- `ensure` не запускает второй daemon, если healthy daemon уже работает.
- `PADL_DAEMON_ENABLED=0` работает как kill switch.
- При hard crash система возвращается в рабочее состояние из env defaults.
- README описывает штатный self-healing flow и аварийный manual flow.

## Риски

- Long-running daemon может потреблять Trigger.dev credits постоянно.
- Без внешней durable БД нельзя гарантировать exactly-once после hard crash.
- Потеря filesystem между runs может сбросить настройки и дедупликацию уведомлений.
- Heartbeat через Trigger Management API добавляет зависимость от API даже для observability.
- `ensure` может отменить живой daemon, если heartbeat долго не обновлялся из-за API-проблемы; поэтому нужны conservative thresholds.
- Telegram long polling конфликтует с webhook и локальным `python -m padlbot`; startup guard должен удалять webhook, а документация должна предупреждать не держать локальный polling одновременно с Trigger daemon.

## Решение

Выбрать Trigger.dev-only self-healing daemon как v2 целевой full-bot design. Supabase удаляется из архитектуры. Trigger.dev используется не только как scheduler, но и как supervisor: scheduled `ensure` поддерживает желаемое состояние, long-running `daemon` выполняет исходную модель бота, heartbeat в metadata связывает их.

Это не максимальная надежность по данным, зато это самый прямой путь к требованию: "процесс должен быть долгоиграющим как в оригинале" и "возвращение работоспособности должно быть самозапускающимся" без Supabase.
