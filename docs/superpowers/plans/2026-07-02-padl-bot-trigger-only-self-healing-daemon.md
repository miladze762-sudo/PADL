# План реализации самовосстанавливающегося демона PADL BOT в Trigger.dev

> **Для агентных исполнителей:** обязательный под-навык: используйте `superpowers:subagent-driven-development` (рекомендуется) или `superpowers:executing-plans`, чтобы выполнять этот план по задачам. Шаги используют checkbox-синтаксис (`- [ ]`) для отслеживания.

**Цель:** запустить PADL BOT в Trigger.dev как долгоживущий самовосстанавливающийся демон без Supabase, webhook backend-сервера и облачного SMS-бронирования.

**Архитектура:** Trigger.dev публикует две задачи: `padl-bot-daemon` держит Python-процесс долгого опроса через `@trigger.dev/python`, а `padl-bot-ensure-daemon` раз в минуту классифицирует активные runs через Management API и запускает или отменяет демон. Python-демон использует существующие `Storage`, `OutdoorApiClient`, `TelegramBot` и `SearchManager`, пишет прикладной heartbeat в метаданные run и хранит состояние best-effort в SQLite.

**Технический стек:** TypeScript, Trigger.dev SDK 4.4.6, `@trigger.dev/python` 4.4.6, Vitest, Python 3, `asyncio`, `aiohttp`, SQLite, `unittest`.

---

## Структура файлов

- Создать `tsconfig.json`: минимальная TypeScript-конфигурация для Vitest и файлов Trigger tasks.
- Изменить `package.json`: добавить `@trigger.dev/python`, `vitest`, `typescript`, `@types/node`, `test:trigger`, `trigger:dry-run`.
- Изменить `package-lock.json`: обновить lockfile через `npm install`.
- Изменить `trigger.config.ts`: подключить `pythonExtension` и включить `padlbot/**/*.py`, `src/trigger/**/*.py`, `requirements.txt` в Trigger build.
- Удалить `src/trigger/example.ts`: убрать демонстрационную task, чтобы deploy публиковал только целевые tasks.
- Создать `src/trigger/padlBotDaemonRuntime.ts`: чистый TypeScript-слой для разбора env, классификации runs, планирования действий supervisor и формирования daemon trigger request.
- Создать `src/trigger/padlBotDaemonRuntime.test.ts`: Vitest-покрытие для env contract, активных statuses, metadata retrieval policy и решений supervisor.
- Создать `src/trigger/padlBotDaemon.ts`: Trigger.dev `task` и `schedules.task`, тонкий SDK adapter вокруг runtime helpers.
- Создать `src/trigger/run_padl_bot.py`: маленький wrapper для `python.runScript`.
- Создать `padlbot/trigger_daemon.py`: entrypoint для cloud-only демона, heartbeat reporter, корректное завершение, плановая ротация и автозапуск для admin.
- Изменить `padlbot/config.py`: расширить env contract и валидацию.
- Изменить `padlbot/telegram_polling.py`: `deleteWebhook`, устойчивый порядок offset, обнаружение Telegram 409 conflict, runtime mode для `/code` и `/resend`, metadata callbacks.
- Изменить `padlbot/service.py`: durable `notified_slots`, отключённые в cloud SMS methods, helper завершения для background tasks.
- Изменить `padlbot/storage.py`: таблицы `telegram_polling_state` и `notified_slots`, методы для polling offset и dedupe уведомлений.
- Создать `tests/test_trigger_daemon.py`: проверки запуска Python-демона, heartbeat payload, SMS-disabled mode, admin auto-start и поведения shutdown.
- Создать `tests/test_trigger_daemon_wrapper.py`: тесты wrapper CLI.
- Изменить `tests/test_config.py`, `tests/test_telegram_polling.py`, `tests/test_storage.py`, `tests/test_service.py`: сфокусированное регрессионное покрытие по спецификации.
- Изменить `.env.example`, `README.md`, `README_RU.md`: Trigger.dev env, поток самовосстановления, ограничения восстановления и аварийная остановка.

Не создавать `supabase/functions/telegram-webhook/index.ts`, `supabase/migrations/*` или `padlbot/storage_postgres.py`.

### Задача 1: Упаковка Trigger и тестовый каркас TypeScript

**Файлы:**
- Создать: `tsconfig.json`
- Изменить: `package.json`
- Изменить: `package-lock.json`
- Изменить: `trigger.config.ts`
- Удалить: `src/trigger/example.ts`

- [ ] **Шаг 1: Установить Trigger Python и тестовые зависимости**

Запустить:

```powershell
npm install "@trigger.dev/python@4.4.6"
npm install --save-dev "vitest@4.1.9" "typescript@6.0.3" "@types/node@26.1.0"
```

Ожидаемый результат: `package.json` и `package-lock.json` изменились; `@trigger.dev/sdk` остался на `4.4.6`.

- [ ] **Шаг 2: Добавить TypeScript-конфиг**

Создать `tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "types": ["node", "vitest/globals"]
  },
  "include": ["src/trigger/**/*.ts", "trigger.config.ts"]
}
```

- [ ] **Шаг 3: Обновить scripts в package и зависимости**

Убедиться, что `package.json` содержит этот блок `scripts`:

```json
{
  "scripts": {
    "trigger:dev": "trigger dev",
    "trigger:deploy": "trigger deploy",
    "trigger:dry-run": "trigger deploy --dry-run",
    "test:trigger": "vitest run \"src/trigger/**/*.test.ts\""
  }
}
```

Убедиться, что зависимости включают:

```json
{
  "dependencies": {
    "@trigger.dev/python": "4.4.6",
    "@trigger.dev/sdk": "4.4.6"
  },
  "devDependencies": {
    "@trigger.dev/build": "4.4.6",
    "@types/node": "26.1.0",
    "trigger.dev": "^4.4.6",
    "typescript": "6.0.3",
    "vitest": "4.1.9"
  }
}
```

- [ ] **Шаг 4: Настроить Python extension**

Заменить `trigger.config.ts` на:

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

- [ ] **Шаг 5: Удалить демонстрационную task**

Удалить `src/trigger/example.ts`.

Запустить:

```powershell
Test-Path .\src\trigger\example.ts
```

Ожидаемый результат: `False`.

- [ ] **Шаг 6: Проверить подключение package**

Запустить:

```powershell
npm run test:trigger
```

Ожидаемый результат: Vitest завершается с кодом `1` и сообщает, что тестовые файлы отсутствуют, пока Задача 2 не создаст `src/trigger/padlBotDaemonRuntime.test.ts`.

- [ ] **Шаг 7: Закоммитить изменения упаковки**

```powershell
git add package.json package-lock.json tsconfig.json trigger.config.ts src/trigger/example.ts
git commit -m "chore: configure trigger python packaging"
```

### Задача 2: Чистый runtime для Trigger supervisor

**Файлы:**
- Создать: `src/trigger/padlBotDaemonRuntime.ts`
- Создать: `src/trigger/padlBotDaemonRuntime.test.ts`

- [ ] **Шаг 1: Написать падающие runtime-тесты**

Создать `src/trigger/padlBotDaemonRuntime.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  ACTIVE_DAEMON_STATUSES,
  DAEMON_RETRY_MAX_ATTEMPTS,
  classifyDaemonRun,
  createDaemonTriggerRequest,
  parseSupervisorEnv,
  planSupervisorActions,
} from "./padlBotDaemonRuntime";

const now = new Date("2026-07-02T12:00:00.000Z");

function run(overrides: Record<string, unknown>) {
  return {
    id: "run_daemon",
    taskIdentifier: "padl-bot-daemon",
    status: "EXECUTING",
    version: "20260702.1",
    createdAt: "2026-07-02T11:55:00.000Z",
    startedAt: "2026-07-02T11:55:10.000Z",
    metadata: {
      kind: "padl-bot-daemon",
      status: "running",
      heartbeatAt: "2026-07-02T11:59:00.000Z",
      generation: "20260702.1",
    },
    ...overrides,
  };
}

describe("parseSupervisorEnv", () => {
  it("uses spec defaults and validates rotation gap", () => {
    const config = parseSupervisorEnv({});

    expect(config.daemonEnabled).toBe(true);
    expect(config.daemonMaxDurationSeconds).toBe(86400);
    expect(config.daemonRotateAfterSeconds).toBe(82800);
    expect(config.heartbeatStaleSeconds).toBe(180);
    expect(config.heartbeatCancelAfterSeconds).toBe(300);
  });

  it("rejects daemon rotation too close to maxDuration", () => {
    expect(() =>
      parseSupervisorEnv({
        DAEMON_MAX_DURATION_SECONDS: "3600",
        PADL_DAEMON_ROTATE_AFTER_SECONDS: "3301",
      }),
    ).toThrow("PADL_DAEMON_ROTATE_AFTER_SECONDS must be at least 600 seconds below DAEMON_MAX_DURATION_SECONDS");
  });
});

describe("classifyDaemonRun", () => {
  it("does not include WAITING in active daemon statuses", () => {
    expect(ACTIVE_DAEMON_STATUSES).toEqual([
      "PENDING_VERSION",
      "DELAYED",
      "QUEUED",
      "DEQUEUED",
      "EXECUTING",
    ]);
  });

  it.each([
    ["QUEUED"],
    ["DELAYED"],
    ["PENDING_VERSION"],
    ["DEQUEUED"],
  ])("classifies %s as starting within the grace window", (status) => {
    expect(
      classifyDaemonRun(run({ status, createdAt: "2026-07-02T11:59:00.000Z", startedAt: null }), {
        now,
        currentVersion: "20260702.1",
        heartbeatStaleSeconds: 180,
        heartbeatCancelAfterSeconds: 300,
        startGraceSeconds: 180,
      }).kind,
    ).toBe("starting");
  });

  it("classifies a starting status older than grace as unknown", () => {
    const classification = classifyDaemonRun(
      run({ status: "DEQUEUED", createdAt: "2026-07-02T11:50:00.000Z", startedAt: null }),
      { now, currentVersion: "20260702.1", heartbeatStaleSeconds: 180, heartbeatCancelAfterSeconds: 300, startGraceSeconds: 180 },
    );

    expect(classification.kind).toBe("unknown");
  });

  it("classifies healthy by metadata heartbeat only", () => {
    const classification = classifyDaemonRun(
      run({ updatedAt: "2026-07-02T11:59:59.000Z" }),
      {
        now,
        currentVersion: "20260702.1",
        heartbeatStaleSeconds: 180,
        heartbeatCancelAfterSeconds: 300,
        startGraceSeconds: 180,
      },
    );

    expect(classification.kind).toBe("healthy");
  });

  it("classifies stale-warn and stale from metadata.heartbeatAt", () => {
    const warn = classifyDaemonRun(
      run({ metadata: { heartbeatAt: "2026-07-02T11:56:30.000Z" } }),
      { now, currentVersion: "20260702.1", heartbeatStaleSeconds: 180, heartbeatCancelAfterSeconds: 300, startGraceSeconds: 180 },
    );
    const stale = classifyDaemonRun(
      run({ metadata: { heartbeatAt: "2026-07-02T11:54:30.000Z" } }),
      { now, currentVersion: "20260702.1", heartbeatStaleSeconds: 180, heartbeatCancelAfterSeconds: 300, startGraceSeconds: 180 },
    );

    expect(warn.kind).toBe("stale-warn");
    expect(stale.kind).toBe("stale");
  });

  it("classifies missing metadata after grace as unknown", () => {
    const classification = classifyDaemonRun(
      run({ metadata: null, createdAt: "2026-07-02T11:50:00.000Z", startedAt: "2026-07-02T11:50:00.000Z" }),
      { now, currentVersion: "20260702.1", heartbeatStaleSeconds: 180, heartbeatCancelAfterSeconds: 300, startGraceSeconds: 180 },
    );

    expect(classification.kind).toBe("unknown");
  });

  it("classifies old-version and unexpected SDK statuses", () => {
    const common = { now, currentVersion: "20260702.1", heartbeatStaleSeconds: 180, heartbeatCancelAfterSeconds: 300, startGraceSeconds: 180 };

    expect(classifyDaemonRun(run({ version: "20260701.1" }), common).kind).toBe("old-version");
    expect(classifyDaemonRun(run({ status: "WAITING" }), common).kind).toBe("unknown");
  });
});

describe("planSupervisorActions", () => {
  const config = parseSupervisorEnv({});

  it("triggers daemon when no active candidates exist", () => {
    expect(
      planSupervisorActions({
        candidates: [],
        currentVersion: "20260702.1",
        ensureRunId: "run_ensure",
        now,
        config,
      }),
    ).toMatchObject({ status: "missing", startDaemon: true, startReason: "missing" });
  });

  it("keeps healthy and starting candidates", () => {
    expect(planSupervisorActions({ candidates: [run({})], currentVersion: "20260702.1", ensureRunId: "run_ensure", now, config }).status).toBe("healthy");
    expect(planSupervisorActions({ candidates: [run({ metadata: null, createdAt: "2026-07-02T11:59:00.000Z" })], currentVersion: "20260702.1", ensureRunId: "run_ensure", now, config }).status).toBe("starting");
  });

  it("does not start a duplicate daemon when classification is unknown", () => {
    const plan = planSupervisorActions({
      candidates: [run({ metadata: null, createdAt: "2026-07-02T11:50:00.000Z" })],
      currentVersion: "20260702.1",
      ensureRunId: "run_ensure",
      now,
      config,
    });

    expect(plan.status).toBe("unknown");
    expect(plan.startDaemon).toBe(false);
  });

  it("cancels stale and old-version candidates before restart", () => {
    const stale = run({ id: "run_stale", metadata: { heartbeatAt: "2026-07-02T11:54:00.000Z" } });
    const old = run({ id: "run_old", version: "20260701.1" });

    expect(planSupervisorActions({ candidates: [stale], currentVersion: "20260702.1", ensureRunId: "run_ensure", now, config })).toMatchObject({
      status: "stale",
      cancelRunIds: ["run_stale"],
      startDaemon: true,
      startReason: "stale",
    });
    expect(planSupervisorActions({ candidates: [old], currentVersion: "20260702.1", ensureRunId: "run_ensure", now, config })).toMatchObject({
      status: "old-version",
      cancelRunIds: ["run_old"],
      startDaemon: true,
      startReason: "old-version",
    });
  });

  it("cancels duplicate healthy runs and keeps the newest startedAt", () => {
    const plan = planSupervisorActions({
      candidates: [
        run({ id: "run_old", startedAt: "2026-07-02T11:50:00.000Z" }),
        run({ id: "run_new", startedAt: "2026-07-02T11:55:00.000Z" }),
      ],
      currentVersion: "20260702.1",
      ensureRunId: "run_ensure",
      now,
      config,
    });

    expect(plan.status).toBe("duplicates-canceled");
    expect(plan.cancelRunIds).toEqual(["run_old"]);
    expect(plan.startDaemon).toBe(false);
  });

  it("does not start a replacement when a healthy run exists beside stale duplicates", () => {
    const plan = planSupervisorActions({
      candidates: [
        run({ id: "run_healthy", startedAt: "2026-07-02T11:55:00.000Z" }),
        run({ id: "run_stale", metadata: { heartbeatAt: "2026-07-02T11:54:00.000Z" } }),
      ],
      currentVersion: "20260702.1",
      ensureRunId: "run_ensure",
      now,
      config,
    });

    expect(plan.status).toBe("duplicates-canceled");
    expect(plan.cancelRunIds).toEqual(["run_stale"]);
    expect(plan.startDaemon).toBe(false);
    expect(plan.keptRunId).toBe("run_healthy");
  });

  it("honors daemon kill switch and optional stop", () => {
    const disabled = parseSupervisorEnv({ PADL_DAEMON_ENABLED: "0" });
    const stopDisabled = parseSupervisorEnv({ PADL_DAEMON_ENABLED: "0", PADL_DAEMON_STOP_WHEN_DISABLED: "1" });

    expect(planSupervisorActions({ candidates: [run({ id: "run_live" })], currentVersion: "20260702.1", ensureRunId: "run_ensure", now, config: disabled })).toMatchObject({
      status: "disabled",
      cancelRunIds: [],
      startDaemon: false,
    });
    expect(planSupervisorActions({ candidates: [run({ id: "run_live" })], currentVersion: "20260702.1", ensureRunId: "run_ensure", now, config: stopDisabled })).toMatchObject({
      status: "disabled-stopped",
      cancelRunIds: ["run_live"],
      startDaemon: false,
    });
  });
});

describe("createDaemonTriggerRequest", () => {
  it("uses minute-scoped idempotency and daemon generation payload", () => {
    const request = createDaemonTriggerRequest({
      reason: "missing",
      ensureRunId: "run_ensure",
      generation: "20260702.1",
      now,
      config: parseSupervisorEnv({}),
    });

    expect(request.payload.reason).toBe("missing");
    expect(request.options.idempotencyKey).toBe("padl-bot-daemon-start-2026-07-02T12:00");
    expect(request.options.concurrencyKey).toBe("padl-bot-daemon-production");
    expect(request.options.maxDuration).toBe(86400);
    expect(request.payload.generation).toBe("20260702.1");
  });

  it("pins daemon retry policy to one attempt", () => {
    expect(DAEMON_RETRY_MAX_ATTEMPTS).toBe(1);
  });
});
```

- [ ] **Шаг 2: Запустить runtime-тесты и проверить RED**

Запустить:

```powershell
npm run test:trigger
```

Ожидаемый результат: FAIL с `Cannot find module './padlBotDaemonRuntime'`.

- [ ] **Шаг 3: Реализовать вспомогательные функции runtime**

Создать `src/trigger/padlBotDaemonRuntime.ts`:

```ts
export const DAEMON_TASK_ID = "padl-bot-daemon";
export const ENSURE_TASK_ID = "padl-bot-ensure-daemon";
export const DAEMON_QUEUE_NAME = "padl-bot-daemon";
export const ENSURE_QUEUE_NAME = "padl-bot-ensure-daemon";
export const DAEMON_RETRY_MAX_ATTEMPTS = 1;
export const ACTIVE_DAEMON_STATUSES = [
  "PENDING_VERSION",
  "DELAYED",
  "QUEUED",
  "DEQUEUED",
  "EXECUTING",
] as const;

export type DaemonRunClassificationKind =
  | "healthy"
  | "starting"
  | "stale-warn"
  | "stale"
  | "old-version"
  | "duplicate"
  | "unknown";

export type SupervisorStatus =
  | "healthy"
  | "starting"
  | "stale-warn"
  | "stale"
  | "old-version"
  | "duplicates-canceled"
  | "unknown"
  | "missing"
  | "disabled"
  | "disabled-stopped";

export type DaemonStartReason = "missing" | "stale" | "old-version" | "manual-restart";

export interface SupervisorConfig {
  daemonEnabled: boolean;
  daemonStopWhenDisabled: boolean;
  daemonMaxDurationSeconds: number;
  daemonRotateAfterSeconds: number;
  heartbeatSeconds: number;
  heartbeatStaleSeconds: number;
  heartbeatCancelAfterSeconds: number;
  heartbeatMaxFailures: number;
  startGraceSeconds: number;
}

export interface DaemonRun {
  id: string;
  taskIdentifier?: string;
  status: string;
  version?: string;
  createdAt: string | Date;
  startedAt?: string | Date | null;
  metadata?: Record<string, unknown> | null;
}

export interface ClassificationOptions {
  now: Date;
  currentVersion: string;
  heartbeatStaleSeconds: number;
  heartbeatCancelAfterSeconds: number;
  startGraceSeconds: number;
}

export interface DaemonRunClassification {
  kind: DaemonRunClassificationKind;
  run: DaemonRun;
  heartbeatAgeSeconds?: number;
  ageSeconds?: number;
  warning?: string;
}

export interface SupervisorPlan {
  status: SupervisorStatus;
  cancelRunIds: string[];
  startDaemon: boolean;
  startReason?: DaemonStartReason;
  warnings: string[];
  keptRunId?: string;
}

export function parseSupervisorEnv(env: Record<string, string | undefined>): SupervisorConfig {
  const config: SupervisorConfig = {
    daemonEnabled: boolEnv(env.PADL_DAEMON_ENABLED, true),
    daemonStopWhenDisabled: boolEnv(env.PADL_DAEMON_STOP_WHEN_DISABLED, false),
    daemonMaxDurationSeconds: intEnv(env.DAEMON_MAX_DURATION_SECONDS, 86400),
    daemonRotateAfterSeconds: intEnv(env.PADL_DAEMON_ROTATE_AFTER_SECONDS, 82800),
    heartbeatSeconds: intEnv(env.PADL_HEARTBEAT_SECONDS, 30),
    heartbeatStaleSeconds: intEnv(env.PADL_HEARTBEAT_STALE_SECONDS, 180),
    heartbeatCancelAfterSeconds: intEnv(env.PADL_HEARTBEAT_CANCEL_AFTER_SECONDS, 300),
    heartbeatMaxFailures: intEnv(env.PADL_HEARTBEAT_MAX_FAILURES, 10),
    startGraceSeconds: intEnv(env.PADL_START_GRACE_SECONDS, 180),
  };

  if (config.daemonRotateAfterSeconds >= config.daemonMaxDurationSeconds - 600) {
    throw new Error("PADL_DAEMON_ROTATE_AFTER_SECONDS must be at least 600 seconds below DAEMON_MAX_DURATION_SECONDS");
  }
  if (config.heartbeatStaleSeconds <= config.heartbeatSeconds) {
    throw new Error("PADL_HEARTBEAT_STALE_SECONDS must be greater than PADL_HEARTBEAT_SECONDS");
  }
  if (config.heartbeatCancelAfterSeconds <= config.heartbeatStaleSeconds) {
    throw new Error("PADL_HEARTBEAT_CANCEL_AFTER_SECONDS must be greater than PADL_HEARTBEAT_STALE_SECONDS");
  }

  return config;
}

export function classifyDaemonRun(
  run: DaemonRun,
  options: ClassificationOptions,
): DaemonRunClassification {
  const ageSeconds = secondsBetween(run.startedAt ?? run.createdAt, options.now);

  if (run.version && run.version !== options.currentVersion) {
    return { kind: "old-version", run, ageSeconds };
  }
  if (run.status === "QUEUED" || run.status === "DELAYED" || run.status === "PENDING_VERSION" || run.status === "DEQUEUED") {
    if (ageSeconds >= options.startGraceSeconds) {
      return { kind: "unknown", run, ageSeconds, warning: `${run.status} exceeded start grace period` };
    }
    return { kind: "starting", run, ageSeconds };
  }
  if (run.status !== "EXECUTING") {
    return { kind: "unknown", run, ageSeconds, warning: `unexpected active status ${run.status}` };
  }

  const heartbeatAt = typeof run.metadata?.heartbeatAt === "string" ? run.metadata.heartbeatAt : undefined;
  if (!heartbeatAt) {
    if (ageSeconds < options.startGraceSeconds) {
      return { kind: "starting", run, ageSeconds };
    }
    return { kind: "unknown", run, ageSeconds, warning: "metadata.heartbeatAt is missing" };
  }

  const heartbeatAgeSeconds = secondsBetween(heartbeatAt, options.now);
  if (heartbeatAgeSeconds >= options.heartbeatCancelAfterSeconds) {
    return { kind: "stale", run, heartbeatAgeSeconds, ageSeconds };
  }
  if (heartbeatAgeSeconds >= options.heartbeatStaleSeconds) {
    return { kind: "stale-warn", run, heartbeatAgeSeconds, ageSeconds };
  }
  return { kind: "healthy", run, heartbeatAgeSeconds, ageSeconds };
}

export function planSupervisorActions(input: {
  candidates: DaemonRun[];
  currentVersion: string;
  ensureRunId: string;
  now: Date;
  config: SupervisorConfig;
}): SupervisorPlan {
  const { candidates, currentVersion, now, config } = input;

  if (!config.daemonEnabled) {
    return {
      status: config.daemonStopWhenDisabled ? "disabled-stopped" : "disabled",
      cancelRunIds: config.daemonStopWhenDisabled ? candidates.map((candidate) => candidate.id) : [],
      startDaemon: false,
      warnings: config.daemonStopWhenDisabled ? ["daemon disabled; active candidates will be canceled"] : ["daemon disabled"],
    };
  }

  if (candidates.length === 0) {
    return { status: "missing", cancelRunIds: [], startDaemon: true, startReason: "missing", warnings: [] };
  }

  const classifications = candidates.map((candidate) =>
    classifyDaemonRun(candidate, {
      now,
      currentVersion,
      heartbeatStaleSeconds: config.heartbeatStaleSeconds,
      heartbeatCancelAfterSeconds: config.heartbeatCancelAfterSeconds,
      startGraceSeconds: config.startGraceSeconds,
    }),
  );

  const warnings = classifications.flatMap((classification) => classification.warning ? [classification.warning] : []);
  const unknown = classifications.find((classification) => classification.kind === "unknown");
  if (unknown) {
    return { status: "unknown", cancelRunIds: [], startDaemon: false, warnings };
  }

  const healthy = classifications.filter((classification) => classification.kind === "healthy");
  if (healthy.length >= 1) {
    const sorted = [...healthy].sort((a, b) => timestamp(b.run.startedAt ?? b.run.createdAt) - timestamp(a.run.startedAt ?? a.run.createdAt));
    const kept = sorted[0].run.id;
    const cancelRunIds = classifications
      .filter((classification) => classification.run.id !== kept)
      .map((classification) => classification.run.id);
    if (cancelRunIds.length === 0) {
      return { status: "healthy", cancelRunIds: [], startDaemon: false, warnings, keptRunId: kept };
    }
    return {
      status: "duplicates-canceled",
      cancelRunIds,
      startDaemon: false,
      warnings,
      keptRunId: kept,
    };
  }

  const stale = classifications.filter((classification) => classification.kind === "stale");
  if (stale.length > 0) {
    return { status: "stale", cancelRunIds: stale.map((classification) => classification.run.id), startDaemon: true, startReason: "stale", warnings };
  }

  const oldVersion = classifications.filter((classification) => classification.kind === "old-version");
  if (oldVersion.length > 0) {
    return { status: "old-version", cancelRunIds: oldVersion.map((classification) => classification.run.id), startDaemon: true, startReason: "old-version", warnings };
  }

  if (classifications.some((classification) => classification.kind === "starting")) {
    return { status: "starting", cancelRunIds: [], startDaemon: false, warnings };
  }
  if (classifications.some((classification) => classification.kind === "stale-warn")) {
    return { status: "stale-warn", cancelRunIds: [], startDaemon: false, warnings: [...warnings, "heartbeat stale warning threshold reached"] };
  }

  return { status: "unknown", cancelRunIds: [], startDaemon: false, warnings: [...warnings, "no safe supervisor action"] };
}

export function createDaemonTriggerRequest(input: {
  reason: DaemonStartReason;
  ensureRunId: string;
  generation: string;
  now: Date;
  config: SupervisorConfig;
}) {
  const requestedAt = input.now.toISOString();
  const minute = requestedAt.slice(0, 16);
  return {
    payload: {
      reason: input.reason,
      requestedAt,
      requestedByRunId: input.ensureRunId,
      generation: input.generation,
    },
    options: {
      tags: ["padl-bot", "daemon"],
      concurrencyKey: "padl-bot-daemon-production",
      idempotencyKey: `padl-bot-daemon-start-${minute}`,
      queue: DAEMON_QUEUE_NAME,
      maxDuration: input.config.daemonMaxDurationSeconds,
      maxAttempts: DAEMON_RETRY_MAX_ATTEMPTS,
    },
  };
}

function boolEnv(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined || value === "") {
    return fallback;
  }
  return ["1", "true", "yes", "y", "on"].includes(value.trim().toLowerCase());
}

function intEnv(value: string | undefined, fallback: number): number {
  if (value === undefined || value === "") {
    return fallback;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    throw new Error(`Expected integer env value, got ${value}`);
  }
  return parsed;
}

function secondsBetween(value: string | Date, now: Date): number {
  return Math.max(0, Math.floor((now.getTime() - timestamp(value)) / 1000));
}

function timestamp(value: string | Date): number {
  return value instanceof Date ? value.getTime() : new Date(value).getTime();
}
```

- [ ] **Шаг 4: Запустить runtime-тесты и проверить GREEN**

Запустить:

```powershell
npm run test:trigger
```

Ожидаемый результат: PASS для `src/trigger/padlBotDaemonRuntime.test.ts`.

- [ ] **Шаг 5: Закоммитить вспомогательные функции runtime**

```powershell
git add src/trigger/padlBotDaemonRuntime.ts src/trigger/padlBotDaemonRuntime.test.ts
git commit -m "feat: add trigger daemon supervisor runtime"
```

### Задача 3: Trigger.dev tasks и адаптер SDK

**Файлы:**
- Создать: `src/trigger/padlBotDaemon.ts`
- Изменить: `src/trigger/padlBotDaemonRuntime.test.ts`

- [ ] **Шаг 1: Добавить тесты для констант task и контракта schedule**

Добавить в `src/trigger/padlBotDaemonRuntime.test.ts`:

```ts
import { DAEMON_TASK_CONFIG, ENSURE_DAEMON_CRON } from "./padlBotDaemon";

describe("Trigger task contract", () => {
  it("sets daemon maxDuration above planned rotation and retry to one attempt", () => {
    expect(DAEMON_TASK_CONFIG.id).toBe("padl-bot-daemon");
    expect(DAEMON_TASK_CONFIG.queue).toEqual({ name: "padl-bot-daemon", concurrencyLimit: 1 });
    expect(DAEMON_TASK_CONFIG.retry).toEqual({ maxAttempts: 1 });
    expect(DAEMON_TASK_CONFIG.maxDuration).toBe(86400);
  });

  it("uses declarative schedules.task cron contract", () => {
    expect(ENSURE_DAEMON_CRON).toEqual({
      pattern: "* * * * *",
      timezone: "Europe/Moscow",
      environments: ["PRODUCTION"],
    });
  });
});
```

- [ ] **Шаг 2: Запустить тесты контракта task и проверить RED**

Запустить:

```powershell
npm run test:trigger
```

Ожидаемый результат: FAIL с `Cannot find module './padlBotDaemon'`.

- [ ] **Шаг 3: Реализовать файл Trigger task**

Создать `src/trigger/padlBotDaemon.ts`:

```ts
import { logger, runs, schedules, task } from "@trigger.dev/sdk";
import { python } from "@trigger.dev/python";
import {
  ACTIVE_DAEMON_STATUSES,
  DAEMON_QUEUE_NAME,
  DAEMON_RETRY_MAX_ATTEMPTS,
  DAEMON_TASK_ID,
  ENSURE_QUEUE_NAME,
  ENSURE_TASK_ID,
  createDaemonTriggerRequest,
  parseSupervisorEnv,
  planSupervisorActions,
  type DaemonRun,
} from "./padlBotDaemonRuntime";

export const DAEMON_TASK_CONFIG = {
  id: DAEMON_TASK_ID,
  queue: { name: DAEMON_QUEUE_NAME, concurrencyLimit: 1 },
  maxDuration: 86400,
  retry: { maxAttempts: DAEMON_RETRY_MAX_ATTEMPTS },
} as const;

export const ENSURE_DAEMON_CRON = {
  pattern: "* * * * *",
  timezone: "Europe/Moscow",
  environments: ["PRODUCTION"],
} as const;

export const padlBotDaemon = task({
  ...DAEMON_TASK_CONFIG,
  run: async (payload: { reason?: string; generation?: string }, { ctx }) => {
    const config = parseSupervisorEnv(process.env);
    const env = {
      ...process.env,
      TRIGGER_RUN_ID: ctx.run.id,
      PADL_TRIGGER_TASK_ID: DAEMON_TASK_ID,
      PADL_RUNTIME_MODE: "trigger-daemon",
      PADL_DISABLE_SMS_WEBHOOK: "1",
      PADL_DELETE_WEBHOOK_ON_START: "1",
      PADL_HEARTBEAT_SECONDS: String(config.heartbeatSeconds),
      PADL_HEARTBEAT_MAX_FAILURES: String(config.heartbeatMaxFailures),
      PADL_DAEMON_GENERATION: payload.generation ?? ctx.run.version ?? "unknown",
      PADL_DAEMON_ROTATE_AFTER_SECONDS: String(config.daemonRotateAfterSeconds),
    };

    const result = await python.runScript("./src/trigger/run_padl_bot.py", ["daemon"], { env });
    if (result.exitCode !== 0) {
      throw new Error(`PADL daemon exited with code ${result.exitCode}`);
    }
    return { ok: true, reason: payload.reason ?? "manual-restart" };
  },
});

export const ensureDaemon = schedules.task({
  id: ENSURE_TASK_ID,
  cron: ENSURE_DAEMON_CRON,
  ttl: "1m",
  queue: { name: ENSURE_QUEUE_NAME, concurrencyLimit: 1 },
  run: async (_payload, { ctx }) => {
    const config = parseSupervisorEnv(process.env);
    const now = new Date();
    const currentVersion = ctx.run.version ?? (await runs.retrieve(ctx.run.id)).version ?? "unknown";
    const candidates = await retrieveActiveDaemonRuns();
    const plan = planSupervisorActions({
      candidates,
      currentVersion,
      ensureRunId: ctx.run.id,
      now,
      config,
    });

    for (const runId of plan.cancelRunIds) {
      await runs.cancel(runId);
    }

    if (plan.startDaemon && plan.startReason) {
      const request = createDaemonTriggerRequest({
        reason: plan.startReason,
        ensureRunId: ctx.run.id,
        generation: currentVersion,
        now,
        config,
      });
      await padlBotDaemon.trigger(request.payload, request.options);
    }

    logger.log("PADL daemon supervisor summary", plan);
    return plan;
  },
});

async function retrieveActiveDaemonRuns(): Promise<DaemonRun[]> {
  const page = await runs.list({
    taskIdentifier: DAEMON_TASK_ID,
    status: [...ACTIVE_DAEMON_STATUSES],
  });

  const listed = page.data ?? [];
  const detailed: DaemonRun[] = [];
  for (const candidate of listed) {
    try {
      const run = await runs.retrieve(candidate.id);
      detailed.push({
        id: run.id,
        taskIdentifier: run.taskIdentifier,
        status: run.status,
        version: run.version,
        createdAt: run.createdAt,
        startedAt: run.startedAt,
        metadata: run.metadata ?? null,
      });
    } catch (error) {
      detailed.push({
        id: candidate.id,
        taskIdentifier: candidate.taskIdentifier,
        status: candidate.status,
        version: candidate.version,
        createdAt: candidate.createdAt,
        startedAt: candidate.startedAt,
        metadata: null,
      });
      logger.warn("Failed to retrieve daemon run metadata", { runId: candidate.id, error });
    }
  }
  return detailed;
}
```

- [ ] **Шаг 4: Запустить TypeScript-тесты и проверить границу статусов SDK**

Запустить:

```powershell
npm run test:trigger
```

Ожидаемый результат: PASS. `ACTIVE_DAEMON_STATUSES` должен содержать только статусы, которые принимает установленный Trigger.dev SDK 4.4.6. Оставить JS-оператор spread для изменяемого массива на границе `runs.list`:

```ts
status: [...ACTIVE_DAEMON_STATUSES],
```

В `ACTIVE_DAEMON_STATUSES` не должны появляться строки `WAITING`, `REATTEMPTING` или `FROZEN`.

- [ ] **Шаг 5: Закоммитить слой tasks**

```powershell
git add src/trigger/padlBotDaemon.ts src/trigger/padlBotDaemonRuntime.test.ts
git commit -m "feat: add trigger daemon tasks"
```

### Задача 4: Контракт env для Config

**Файлы:**
- Изменить: `padlbot/config.py`
- Изменить: `tests/test_config.py`

- [ ] **Шаг 1: Добавить падающие config-тесты**

Вставить эти методы в существующий класс `ConfigTests` в `tests/test_config.py` перед `if __name__ == "__main__":`:

```python
    def test_trigger_daemon_env_contract_is_parsed(self):
        env_path = Path.cwd() / ".tmp" / "test-trigger-config.env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            env_path.write_text(
                "\n".join(
                    [
                        "TELEGRAM_BOT_TOKEN=token",
                        "TRIGGER_SECRET_KEY=tr_secret",
                        "PADL_RUNTIME_MODE=trigger-daemon",
                        "PADL_DISABLE_SMS_WEBHOOK=1",
                        "PADL_DAEMON_ENABLED=1",
                        "PADL_DAEMON_STOP_WHEN_DISABLED=0",
                        "PADL_DELETE_WEBHOOK_ON_START=1",
                        "PADL_DROP_PENDING_UPDATES_ON_START=0",
                        "ADMIN_CHAT_ID=100",
                        "AUTO_START_SEARCH=1",
                        "PADL_DEFAULT_VENUE_IDS=12,14,15",
                        "PADL_HEARTBEAT_SECONDS=30",
                        "PADL_HEARTBEAT_STALE_SECONDS=180",
                        "PADL_HEARTBEAT_CANCEL_AFTER_SECONDS=300",
                        "PADL_HEARTBEAT_MAX_FAILURES=10",
                        "PADL_START_GRACE_SECONDS=180",
                        "PADL_DAEMON_ROTATE_AFTER_SECONDS=82800",
                        "DAEMON_MAX_DURATION_SECONDS=86400",
                        "PADL_TELEGRAM_CONFLICT_EXIT_SECONDS=120",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = Config.from_env(env_path)
        finally:
            env_path.unlink(missing_ok=True)

        self.assertEqual(config.runtime_mode, "trigger-daemon")
        self.assertTrue(config.disable_sms_webhook)
        self.assertTrue(config.daemon_enabled)
        self.assertFalse(config.daemon_stop_when_disabled)
        self.assertTrue(config.delete_webhook_on_start)
        self.assertFalse(config.drop_pending_updates_on_start)
        self.assertEqual(config.default_venue_ids, (12, 14, 15))
        self.assertEqual(config.heartbeat_seconds, 30)
        self.assertEqual(config.heartbeat_stale_seconds, 180)
        self.assertEqual(config.heartbeat_cancel_after_seconds, 300)
        self.assertEqual(config.heartbeat_max_failures, 10)
        self.assertEqual(config.start_grace_seconds, 180)
        self.assertEqual(config.daemon_rotate_after_seconds, 82800)
        self.assertEqual(config.daemon_max_duration_seconds, 86400)
        self.assertEqual(config.telegram_conflict_exit_seconds, 120)

    def test_trigger_daemon_requires_secret(self):
        env_path = Path.cwd() / ".tmp" / "test-trigger-missing-secret.env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            env_path.write_text(
                "TELEGRAM_BOT_TOKEN=token\nPADL_RUNTIME_MODE=trigger-daemon\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(Exception, "TRIGGER_SECRET_KEY is required"):
                    Config.from_env(env_path)
        finally:
            env_path.unlink(missing_ok=True)

    def test_auto_start_requires_admin_chat_id(self):
        env_path = Path.cwd() / ".tmp" / "test-trigger-missing-admin.env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            env_path.write_text(
                "TELEGRAM_BOT_TOKEN=token\nAUTO_START_SEARCH=1\nPADL_DEFAULT_VENUE_IDS=12\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(Exception, "ADMIN_CHAT_ID is required"):
                    Config.from_env(env_path)
        finally:
            env_path.unlink(missing_ok=True)
```

- [ ] **Шаг 2: Запустить config-тесты и проверить RED**

Запустить:

```powershell
python -m unittest tests.test_config -v
```

Ожидаемый результат: FAIL, потому что в `Config` ещё нет полей trigger daemon.

- [ ] **Шаг 3: Расширить dataclass `Config` и parser**

В `padlbot/config.py` добавить:

```python
def _list_int_value(value: str | None) -> tuple[int, ...]:
    if value is None or value.strip() == "":
        return ()
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())
```

Добавить поля в `Config`:

```python
    trigger_secret_key: str = ""
    runtime_mode: str = "local"
    disable_sms_webhook: bool = False
    daemon_enabled: bool = True
    daemon_stop_when_disabled: bool = False
    delete_webhook_on_start: bool = False
    drop_pending_updates_on_start: bool = False
    default_venue_ids: tuple[int, ...] = ()
    heartbeat_seconds: int = 30
    heartbeat_stale_seconds: int = 180
    heartbeat_cancel_after_seconds: int = 300
    heartbeat_max_failures: int = 10
    start_grace_seconds: int = 180
    daemon_rotate_after_seconds: int = 82800
    daemon_max_duration_seconds: int = 86400
    telegram_conflict_exit_seconds: int = 120
```

В `Config.from_env` разобрать и проверить:

```python
        runtime_mode = merged.get("PADL_RUNTIME_MODE", "local").strip() or "local"
        trigger_secret_key = merged.get("TRIGGER_SECRET_KEY", "").strip()
        auto_start_search = _bool_value(merged.get("AUTO_START_SEARCH"), default=False)
        admin_chat_id = _int_value(merged.get("ADMIN_CHAT_ID"))
        disable_sms_webhook = _bool_value(merged.get("PADL_DISABLE_SMS_WEBHOOK"), default=False)
        daemon_enabled = _bool_value(merged.get("PADL_DAEMON_ENABLED"), default=True)
        daemon_stop_when_disabled = _bool_value(merged.get("PADL_DAEMON_STOP_WHEN_DISABLED"), default=False)
        delete_webhook_on_start = _bool_value(merged.get("PADL_DELETE_WEBHOOK_ON_START"), default=False)
        drop_pending_updates_on_start = _bool_value(merged.get("PADL_DROP_PENDING_UPDATES_ON_START"), default=False)
        default_venue_ids = _list_int_value(merged.get("PADL_DEFAULT_VENUE_IDS"))
        heartbeat_seconds = int(merged.get("PADL_HEARTBEAT_SECONDS", "30"))
        heartbeat_stale_seconds = int(merged.get("PADL_HEARTBEAT_STALE_SECONDS", "180"))
        heartbeat_cancel_after_seconds = int(merged.get("PADL_HEARTBEAT_CANCEL_AFTER_SECONDS", "300"))
        heartbeat_max_failures = int(merged.get("PADL_HEARTBEAT_MAX_FAILURES", "10"))
        start_grace_seconds = int(merged.get("PADL_START_GRACE_SECONDS", "180"))
        daemon_rotate_after_seconds = int(merged.get("PADL_DAEMON_ROTATE_AFTER_SECONDS", "82800"))
        daemon_max_duration_seconds = int(merged.get("DAEMON_MAX_DURATION_SECONDS", "86400"))
        telegram_conflict_exit_seconds = int(merged.get("PADL_TELEGRAM_CONFLICT_EXIT_SECONDS", "120"))

        if runtime_mode == "trigger-daemon" and not trigger_secret_key:
            raise ConfigError("TRIGGER_SECRET_KEY is required in trigger-daemon mode")
        if auto_start_search and admin_chat_id is None:
            raise ConfigError("ADMIN_CHAT_ID is required when AUTO_START_SEARCH=1")
        if auto_start_search and not default_venue_ids:
            raise ConfigError("PADL_DEFAULT_VENUE_IDS is required when AUTO_START_SEARCH=1")
        if daemon_rotate_after_seconds >= daemon_max_duration_seconds - 600:
            raise ConfigError("PADL_DAEMON_ROTATE_AFTER_SECONDS must be at least 600 seconds below DAEMON_MAX_DURATION_SECONDS")
        if heartbeat_stale_seconds <= heartbeat_seconds:
            raise ConfigError("PADL_HEARTBEAT_STALE_SECONDS must be greater than PADL_HEARTBEAT_SECONDS")
        if heartbeat_cancel_after_seconds <= heartbeat_stale_seconds:
            raise ConfigError("PADL_HEARTBEAT_CANCEL_AFTER_SECONDS must be greater than PADL_HEARTBEAT_STALE_SECONDS")
```

Передать все разобранные значения в `cls(...)`. Возвращаемый объект должен явно задавать `admin_chat_id`, `auto_start_search` и каждое новое trigger-поле, а не полагаться на значения по умолчанию dataclass:

```python
            admin_chat_id=admin_chat_id,
            auto_start_search=auto_start_search,
            trigger_secret_key=trigger_secret_key,
            runtime_mode=runtime_mode,
            disable_sms_webhook=disable_sms_webhook,
            daemon_enabled=daemon_enabled,
            daemon_stop_when_disabled=daemon_stop_when_disabled,
            delete_webhook_on_start=delete_webhook_on_start,
            drop_pending_updates_on_start=drop_pending_updates_on_start,
            default_venue_ids=default_venue_ids,
            heartbeat_seconds=heartbeat_seconds,
            heartbeat_stale_seconds=heartbeat_stale_seconds,
            heartbeat_cancel_after_seconds=heartbeat_cancel_after_seconds,
            heartbeat_max_failures=heartbeat_max_failures,
            start_grace_seconds=start_grace_seconds,
            daemon_rotate_after_seconds=daemon_rotate_after_seconds,
            daemon_max_duration_seconds=daemon_max_duration_seconds,
            telegram_conflict_exit_seconds=telegram_conflict_exit_seconds,
```

- [ ] **Шаг 4: Запустить config-тесты и проверить GREEN**

Запустить:

```powershell
python -m unittest tests.test_config -v
```

Ожидаемый результат: PASS.

- [ ] **Шаг 5: Закоммитить изменения config**

```powershell
git add padlbot/config.py tests/test_config.py
git commit -m "feat: add trigger daemon config contract"
```

### Задача 5: Best-effort state в SQLite

**Файлы:**
- Изменить: `padlbot/storage.py`
- Изменить: `tests/test_storage.py`

- [ ] **Шаг 1: Добавить падающие storage-тесты**

Вставить эти методы в существующий класс `StorageTests` в `tests/test_storage.py` перед `if __name__ == "__main__":`:

```python
    def test_telegram_polling_state_round_trip(self):
        db_path = Path.cwd() / "test-polling-state.db"
        try:
            storage = Storage(db_path)
            storage.initialize()

            self.assertIsNone(storage.get_last_update_id())
            storage.save_last_update_id(123456)

            self.assertEqual(storage.get_last_update_id(), 123456)
        finally:
            db_path.unlink(missing_ok=True)

    def test_notified_slots_suppress_duplicates_after_restart(self):
        db_path = Path.cwd() / "test-notified-slots.db"
        try:
            storage = Storage(db_path)
            storage.initialize()

            self.assertTrue(storage.mark_slot_notified(100, "slot-1"))
            self.assertFalse(storage.mark_slot_notified(100, "slot-1"))
            self.assertTrue(storage.mark_slot_notified(100, "slot-2"))
        finally:
            db_path.unlink(missing_ok=True)
```

- [ ] **Шаг 2: Запустить storage-тесты и проверить RED**

Запустить:

```powershell
python -m unittest tests.test_storage -v
```

Ожидаемый результат: FAIL, потому что в `Storage` ещё нет polling state и методов для notified slots.

- [ ] **Шаг 3: Добавить таблицы и методы**

В `Storage.initialize()` расширить `executescript`:

```sql
                CREATE TABLE IF NOT EXISTS notified_slots (
                    chat_id INTEGER NOT NULL,
                    slot_key TEXT NOT NULL,
                    first_notified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(chat_id, slot_key)
                );

                CREATE TABLE IF NOT EXISTS telegram_polling_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_update_id INTEGER,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
```

Добавить методы в `Storage`:

```python
    def get_last_update_id(self) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT last_update_id FROM telegram_polling_state WHERE id = 1"
            ).fetchone()
        if row is None or row["last_update_id"] is None:
            return None
        return int(row["last_update_id"])

    def save_last_update_id(self, update_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO telegram_polling_state (id, last_update_id, updated_at)
                VALUES (1, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    last_update_id = excluded.last_update_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (update_id,),
            )

    def mark_slot_notified(self, chat_id: int, slot_key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO notified_slots (chat_id, slot_key)
                VALUES (?, ?)
                """,
                (chat_id, slot_key),
            )
            return cursor.rowcount == 1
```

- [ ] **Шаг 4: Запустить storage-тесты и проверить GREEN**

Запустить:

```powershell
python -m unittest tests.test_storage -v
```

Ожидаемый результат: PASS.

- [ ] **Шаг 5: Закоммитить изменения storage**

```powershell
git add padlbot/storage.py tests/test_storage.py
git commit -m "feat: persist trigger daemon best-effort state"
```

### Задача 6: Контракт Telegram polling

**Файлы:**
- Изменить: `padlbot/telegram_polling.py`
- Изменить: `tests/test_telegram_polling.py`

- [ ] **Шаг 1: Добавить падающие polling-тесты**

Вставить этот блок в `tests/test_telegram_polling.py` после существующих fake classes и перед `if __name__ == "__main__":`:

```python
from unittest.mock import AsyncMock, patch

from padlbot.telegram_polling import (
    IncomingMessage,
    TelegramBot,
    handle_message,
    is_telegram_conflict_error,
    polling_loop,
)


class FakePollingBot:
    def __init__(self, batches):
        self.batches = list(batches)
        self.offsets = []
        self.deleted_webhooks = []
        self.messages = []

    async def get_updates(self, offset):
        self.offsets.append(offset)
        if not self.batches:
            raise RuntimeError("stop polling")
        return self.batches.pop(0)

    async def send_message(self, chat_id, text):
        self.messages.append({"chat_id": chat_id, "text": text})

    async def delete_webhook(self, *, drop_pending_updates):
        self.deleted_webhooks.append(drop_pending_updates)


class FakePollingStorage:
    def __init__(self, last_update_id=None):
        self.last_update_id = last_update_id
        self.saved_update_ids = []

    def get_last_update_id(self):
        return self.last_update_id

    def save_last_update_id(self, update_id):
        self.last_update_id = update_id
        self.saved_update_ids.append(update_id)


class FakePollingManager:
    def __init__(self):
        self.calls = []

    async def start_search(self, chat_id, preferences):
        self.calls.append((chat_id, preferences))
        return "started"


class TelegramPollingLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_polling_uses_persisted_offset_and_saves_after_success(self):
        bot = FakePollingBot(
            [
                [
                    {
                        "update_id": 100,
                        "message": {"chat": {"id": 200}, "text": "/search"},
                    }
                ]
            ]
        )
        storage = FakePollingStorage(last_update_id=99)
        manager = FakePollingManager()

        with patch("padlbot.telegram_polling.asyncio.sleep", new=AsyncMock(side_effect=RuntimeError("stop polling"))):
            with self.assertRaisesRegex(RuntimeError, "stop polling"):
                await polling_loop(bot=bot, manager=manager, storage=storage)

        self.assertEqual(bot.offsets[0], 100)
        self.assertEqual(storage.saved_update_ids, [100])

    async def test_polling_does_not_advance_offset_when_send_fails(self):
        batches = [
            [
                {
                    "update_id": 100,
                    "message": {"chat": {"id": 200}, "text": "/search"},
                }
            ]
        ]
        storage = FakePollingStorage()

        class FailingSendBot(FakePollingBot):
            async def send_message(self, chat_id, text):
                raise RuntimeError("send failed")

        bot = FailingSendBot(batches)

        sleep = AsyncMock(side_effect=[None, RuntimeError("stop polling")])
        with patch("padlbot.telegram_polling.asyncio.sleep", new=sleep):
            with self.assertRaisesRegex(RuntimeError, "stop polling"):
                await polling_loop(bot=bot, manager=FakePollingManager(), storage=storage)

        self.assertEqual(bot.offsets, [None, None])
        self.assertEqual(storage.saved_update_ids, [])

    async def test_delete_webhook_guard_calls_telegram_api(self):
        calls = []

        class FakeResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def json(self, content_type=None):
                return {"ok": True, "result": True}

        class FakeSession:
            def post(self, url, *, json):
                calls.append({"url": url, "json": json})
                return FakeResponse()

        bot = TelegramBot("token")
        bot.session = FakeSession()
        await bot.delete_webhook(drop_pending_updates=False)

        self.assertTrue(calls[0]["url"].endswith("/deleteWebhook"))
        self.assertEqual(calls[0]["json"], {"drop_pending_updates": False})

    async def test_telegram_conflict_exits_after_configured_threshold(self):
        statuses = []

        class ConflictBot(FakePollingBot):
            async def get_updates(self, offset):
                self.offsets.append(offset)
                raise RuntimeError("Telegram API error: {'error_code': 409, 'description': 'Conflict: terminated by other getUpdates request'}")

        bot = ConflictBot([])

        with self.assertRaisesRegex(RuntimeError, "Conflict"):
            await polling_loop(
                bot=bot,
                manager=FakePollingManager(),
                storage=FakePollingStorage(),
                on_polling_error=lambda status, error: statuses.append((status, error)),
                conflict_exit_seconds=0,
            )

        self.assertTrue(is_telegram_conflict_error(RuntimeError(statuses[0][1])))
        self.assertEqual(statuses[0][0], "conflict")
```

Также вставить этот trigger-daemon command test в существующий класс `TelegramPollingMessageTests`:

```python
    async def test_code_command_is_disabled_in_trigger_daemon_mode(self):
        bot = FakeBot()

        class CloudDisabledManager:
            runtime_mode = "trigger-daemon"

        await handle_message(
            IncomingMessage(chat_id=100, text="/code 1234"),
            bot=bot,
            manager=CloudDisabledManager(),
            storage=None,
        )

        self.assertEqual(
            bot.messages[0]["text"],
            "Автоматическое удержание слотов и СМС-подтверждение в облачном режиме отключены.",
        )
```

- [ ] **Шаг 2: Запустить polling-тесты и проверить RED**

Запустить:

```powershell
python -m unittest tests.test_telegram_polling -v
```

Ожидаемый результат: FAIL, потому что `delete_webhook`, сохранённый offset, обработка Telegram conflict и отключённый в cloud `/code` ещё не реализованы.

- [ ] **Шаг 3: Реализовать Telegram API helpers и offset ordering**

В `padlbot/telegram_polling.py` добавить conflict detector рядом с helpers:

```python
def is_telegram_conflict_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "409" in text and "conflict" in text
```

В `TelegramBot` добавить:

```python
    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        await self._request(
            "deleteWebhook",
            {"drop_pending_updates": drop_pending_updates},
        )
```

Изменить сигнатуру и тело `polling_loop`:

```python
async def polling_loop(
    *,
    bot: TelegramBot,
    manager,
    storage,
    on_update_processed=None,
    on_polling_error=None,
    conflict_exit_seconds: int | None = None,
) -> None:
    last_update_id = storage.get_last_update_id() if hasattr(storage, "get_last_update_id") else None
    offset: int | None = None if last_update_id is None else last_update_id + 1
    conflict_started_at: float | None = None
    while True:
        try:
            updates = await bot.get_updates(offset)
            conflict_started_at = None
            for update in updates:
                update_id = int(update["update_id"])
                message = _extract_message(update)
                if message is not None:
                    await handle_message(message, bot=bot, manager=manager, storage=storage)
                last_update_id = update_id
                offset = update_id + 1
                if hasattr(storage, "save_last_update_id"):
                    storage.save_last_update_id(update_id)
                if on_update_processed is not None:
                    on_update_processed(update_id)
        except asyncio.CancelledError:
            raise
        except RuntimeError as exc:
            if str(exc) == "stop polling":
                raise
            if is_telegram_conflict_error(exc):
                loop = asyncio.get_running_loop()
                if conflict_started_at is None:
                    conflict_started_at = loop.time()
                if on_polling_error is not None:
                    on_polling_error("conflict", str(exc))
                if conflict_exit_seconds is not None and loop.time() - conflict_started_at >= conflict_exit_seconds:
                    raise
                print(f"Telegram polling conflict: {exc}")
                await asyncio.sleep(5)
                continue
            print(f"Telegram polling error: {exc}")
            await asyncio.sleep(5)
        except Exception as exc:
            print(f"Telegram polling error: {exc}")
            await asyncio.sleep(5)
```

- [ ] **Шаг 4: Отключить `/code` и `/resend` в режиме trigger-daemon**

В `handle_message`, перед legacy-обработкой SMS:

```python
    if command in {"/code", "/resend"} and getattr(manager, "runtime_mode", "") == "trigger-daemon":
        await bot.send_message(
            message.chat_id,
            "Автоматическое удержание слотов и СМС-подтверждение в облачном режиме отключены.",
        )
        return
```

- [ ] **Шаг 5: Запустить polling-тесты и проверить GREEN**

Запустить:

```powershell
python -m unittest tests.test_telegram_polling -v
```

Ожидаемый результат: PASS.

- [ ] **Шаг 6: Закоммитить изменения polling**

```powershell
git add padlbot/telegram_polling.py tests/test_telegram_polling.py
git commit -m "feat: make telegram polling trigger-daemon safe"
```

### Задача 7: Cloud state и завершение для SearchManager

**Файлы:**
- Изменить: `padlbot/service.py`
- Изменить: `tests/test_service.py`

- [ ] **Шаг 1: Добавить падающие service-тесты**

Вставить этот блок в `tests/test_service.py` перед `if __name__ == "__main__":`:

```python
class FakeDurableNotificationStorage(FakeMonitoringStorage):
    def __init__(self, preferences):
        super().__init__(preferences)
        self.notified = set()

    def mark_slot_notified(self, chat_id, slot_key):
        key = (chat_id, slot_key)
        if key in self.notified:
            return False
        self.notified.add(key)
        return True


class SearchManagerTriggerModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_notified_slots_use_storage_to_suppress_soft_restart_duplicates(self):
        preferences = SearchPreferences(poll_interval_seconds=0.01)
        storage = FakeDurableNotificationStorage(preferences)
        bot = FakeMonitoringBot()
        manager = SearchManager(api=None, storage=storage, bot=bot, config=None)
        manager.runtime_mode = "trigger-daemon"
        slot = SlotCandidate(
            venue_id=14,
            venue_title="Tretyakovskaya",
            court_id=13,
            court_title="Court 2",
            date_key="2026-06-11",
            event_id=793,
            starts_at="2026-06-11T17:00:00.000+03:00",
            ends_at="2026-06-11T18:00:00.000+03:00",
            duration_minutes=60,
            available_tickets=2,
        )

        first = manager._new_slots_for_notification(100, [slot])
        second = manager._new_slots_for_notification(100, [slot])

        self.assertEqual(first, [slot])
        self.assertEqual(second, [])

    async def test_cancel_all_searches_cancels_running_tasks(self):
        preferences = SearchPreferences(poll_interval_seconds=10)
        storage = FakeMonitoringStorage(preferences)
        bot = FakeMonitoringBot()
        manager = SearchManager(api=None, storage=storage, bot=bot, config=None)
        manager.scanner = FakeMonitoringScanner([[]])
        manager.coordinator = FakeMonitoringCoordinator()

        await manager.start_search(100, preferences)
        await manager.cancel_all_searches()

        self.assertTrue(manager.state.tasks[100].cancelled() or manager.state.tasks[100].done())
```

- [ ] **Шаг 2: Запустить service-тесты и проверить RED**

Запустить:

```powershell
python -m unittest tests.test_service -v
```

Ожидаемый результат: FAIL, потому что durable suppression для уведомлений и `cancel_all_searches` ещё не существуют.

- [ ] **Шаг 3: Добавить runtime mode и helper завершения**

В `SearchManager.__init__` добавить:

```python
        self.runtime_mode = config.runtime_mode if config is not None else "local"
```

Добавить метод:

```python
    async def cancel_all_searches(self) -> None:
        tasks = [task for task in self.state.tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
```

- [ ] **Шаг 4: Использовать SQLite `notified_slots`, если доступно**

Изменить `_new_slots_for_notification`:

```python
    def _new_slots_for_notification(
        self,
        chat_id: int,
        slots: list[SlotCandidate],
    ) -> list[SlotCandidate]:
        notified = self.state.notified_slots.setdefault(chat_id, set())
        new_slots: list[SlotCandidate] = []
        for slot in slots:
            key = self._slot_key(slot)
            storage_key = "|".join(str(part) for part in key)
            if hasattr(self.storage, "mark_slot_notified"):
                if not self.storage.mark_slot_notified(chat_id, storage_key):
                    notified.add(key)
                    continue
            elif key in notified:
                continue
            notified.add(key)
            new_slots.append(slot)
        return new_slots
```

- [ ] **Шаг 5: Запустить service-тесты и проверить GREEN**

Запустить:

```powershell
python -m unittest tests.test_service -v
```

Ожидаемый результат: PASS.

- [ ] **Шаг 6: Закоммитить изменения service**

```powershell
git add padlbot/service.py tests/test_service.py
git commit -m "feat: persist notification dedupe in trigger daemon"
```

### Задача 8: Python Trigger daemon и heartbeat

**Файлы:**
- Создать: `padlbot/trigger_daemon.py`
- Создать: `src/trigger/run_padl_bot.py`
- Создать: `tests/test_trigger_daemon.py`
- Создать: `tests/test_trigger_daemon_wrapper.py`

- [ ] **Шаг 1: Добавить падающие wrapper-тесты**

Создать `tests/test_trigger_daemon_wrapper.py`:

```python
import unittest
from unittest.mock import AsyncMock, patch

from src.trigger import run_padl_bot


class TriggerDaemonWrapperTests(unittest.IsolatedAsyncioTestCase):
    async def test_daemon_command_delegates_to_trigger_daemon(self):
        with patch("padlbot.trigger_daemon.main", new=AsyncMock(return_value=0)) as main:
            exit_code = await run_padl_bot.main(["daemon"])

        self.assertEqual(exit_code, 0)
        main.assert_awaited_once()

    async def test_healthcheck_command_returns_zero(self):
        self.assertEqual(await run_padl_bot.main(["healthcheck"]), 0)

    async def test_unknown_command_returns_two(self):
        self.assertEqual(await run_padl_bot.main(["wat"]), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Шаг 2: Добавить падающие тесты daemon**

Создать `tests/test_trigger_daemon.py`:

```python
import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from padlbot.config import Config
from padlbot.trigger_daemon import HeartbeatReporter, build_heartbeat_payload, exit_reason_for, main


class TriggerDaemonHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeat_payload_contains_no_secrets_or_personal_data(self):
        payload = build_heartbeat_payload(
            status="running",
            generation="20260702.1",
            telegram_polling="active",
            active_search_tasks=1,
            last_update_id=123,
            started_at="2026-07-02T12:00:00Z",
            last_loop_error=None,
        )

        text = repr(payload)
        self.assertEqual(payload["kind"], "padl-bot-daemon")
        self.assertEqual(payload["status"], "running")
        self.assertIn("heartbeatAt", payload)
        self.assertNotIn("TRIGGER_SECRET_KEY", text)
        self.assertNotIn("TELEGRAM_BOT_TOKEN", text)
        self.assertNotIn("phone", text.lower())
        self.assertNotIn("email", text.lower())

    async def test_heartbeat_failure_does_not_raise(self):
        reporter = HeartbeatReporter(
            run_id="run_123",
            secret_key="secret",
            generation="20260702.1",
            max_failures=2,
            request=lambda payload: (_ for _ in ()).throw(RuntimeError("api down")),
        )

        await reporter.update(status="running", active_search_tasks=0)

        self.assertEqual(reporter.failure_count, 1)

    async def test_heartbeat_failure_threshold_marks_reporter_unhealthy(self):
        reporter = HeartbeatReporter(
            run_id="run_123",
            secret_key="secret",
            generation="20260702.1",
            max_failures=1,
            request=lambda payload: (_ for _ in ()).throw(RuntimeError("api down")),
        )

        await reporter.update(status="running", active_search_tasks=0)

        self.assertTrue(reporter.heartbeat_unhealthy)

    async def test_default_request_wraps_payload_in_metadata_body(self):
        sent = []

        class FakeResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def text(self):
                return ""

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            def put(self, url, *, headers, json):
                sent.append({"url": url, "headers": headers, "json": json})
                return FakeResponse()

        reporter = HeartbeatReporter(
            run_id="run_123",
            secret_key="secret",
            generation="20260702.1",
            max_failures=2,
        )

        with patch("padlbot.trigger_daemon.aiohttp.ClientSession", return_value=FakeSession()):
            await reporter._default_request({"heartbeatAt": "2026-07-02T12:00:00Z"})

        self.assertEqual(sent[0]["json"], {"metadata": {"heartbeatAt": "2026-07-02T12:00:00Z"}})

    async def test_polling_conflict_exit_reason_is_explicit(self):
        error = RuntimeError("Telegram API error: {'error_code': 409, 'description': 'Conflict: terminated by other getUpdates request'}")

        self.assertEqual(exit_reason_for(error, rotation_done=False), "telegram-conflict")


class TriggerDaemonStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_trigger_daemon_does_not_start_sms_webhook(self):
        env_path = Path.cwd() / ".tmp" / "test-trigger-daemon.env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(
            "\n".join(
                [
                    "TELEGRAM_BOT_TOKEN=token",
                    "TRIGGER_SECRET_KEY=secret",
                    "TRIGGER_RUN_ID=run_123",
                    "PADL_RUNTIME_MODE=trigger-daemon",
                    "PADL_DISABLE_SMS_WEBHOOK=1",
                    "ADMIN_CHAT_ID=100",
                    "AUTO_START_SEARCH=1",
                    "PADL_DEFAULT_VENUE_IDS=12,14,15",
                    "PADL_DAEMON_ROTATE_AFTER_SECONDS=82800",
                    "DAEMON_MAX_DURATION_SECONDS=86400",
                ]
            ),
            encoding="utf-8",
        )
        try:
            with patch.dict(os.environ, {}, clear=True), patch(
                "padlbot.config.Config.from_env",
                return_value=Config.from_env(env_path),
            ), patch("padlbot.trigger_daemon.start_sms_webhook") as sms, patch(
                "padlbot.trigger_daemon.run_daemon",
                new=AsyncMock(return_value=0),
            ):
                exit_code = await main()
        finally:
            env_path.unlink(missing_ok=True)

        self.assertEqual(exit_code, 0)
        sms.assert_not_called()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Шаг 3: Запустить новые тесты daemon и проверить RED**

Запустить:

```powershell
python -m unittest tests.test_trigger_daemon_wrapper tests.test_trigger_daemon -v
```

Ожидаемый результат: FAIL, потому что `src/trigger/run_padl_bot.py` и `padlbot.trigger_daemon` ещё не существуют.

- [ ] **Шаг 4: Создать Python package markers для wrapper import**

Создать пустые файлы:

```text
src/__init__.py
src/trigger/__init__.py
```

- [ ] **Шаг 5: Реализовать wrapper**

Создать `src/trigger/run_padl_bot.py`:

```python
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "daemon"
    if command == "healthcheck":
        return 0
    if command != "daemon":
        print(f"Unknown command: {command}")
        return 2

    from padlbot.trigger_daemon import main as daemon_main

    return await daemon_main()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Шаг 6: Реализовать heartbeat payload и reporter**

Создать `padlbot/trigger_daemon.py` с этими helper-функциями верхнего уровня:

```python
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable

import aiohttp

from .config import Config
from .outdoor_api import OutdoorApiClient
from .service import SearchManager
from .sms_webhook import start_sms_webhook
from .storage import Storage
from .telegram_polling import TelegramBot, is_telegram_conflict_error, polling_loop


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_heartbeat_payload(
    *,
    status: str,
    generation: str,
    telegram_polling: str,
    active_search_tasks: int,
    last_update_id: int | None = None,
    started_at: str,
    last_loop_error: str | None = None,
    exit_reason: str | None = None,
) -> dict:
    payload = {
        "kind": "padl-bot-daemon",
        "status": status,
        "heartbeatAt": utc_now_iso(),
        "generation": generation,
        "telegramPolling": telegram_polling,
        "activeSearchTasks": active_search_tasks,
        "lastUpdateId": last_update_id,
        "lastLoopError": last_loop_error,
        "startedAt": started_at,
    }
    if exit_reason is not None:
        payload["exitReason"] = exit_reason
    return payload


class HeartbeatReporter:
    def __init__(
        self,
        *,
        run_id: str,
        secret_key: str,
        generation: str,
        max_failures: int,
        request: Callable[[dict], Awaitable[None]] | None = None,
    ):
        self.run_id = run_id
        self.secret_key = secret_key
        self.generation = generation
        self.max_failures = max_failures
        self.failure_count = 0
        self.heartbeat_unhealthy = False
        self._request = request or self._default_request
        self.started_at = utc_now_iso()
        self.last_update_id: int | None = None
        self.telegram_polling = "active"
        self.last_loop_error: str | None = None

    async def update(
        self,
        *,
        status: str,
        active_search_tasks: int,
        telegram_polling: str | None = None,
        last_loop_error: str | None = None,
        exit_reason: str | None = None,
    ) -> None:
        effective_telegram_polling = telegram_polling or self.telegram_polling
        effective_last_loop_error = last_loop_error if last_loop_error is not None else self.last_loop_error
        payload = build_heartbeat_payload(
            status=status,
            generation=self.generation,
            telegram_polling=effective_telegram_polling,
            active_search_tasks=active_search_tasks,
            last_update_id=self.last_update_id,
            started_at=self.started_at,
            last_loop_error=effective_last_loop_error,
            exit_reason=exit_reason,
        )
        try:
            await self._request(payload)
            self.failure_count = 0
            self.heartbeat_unhealthy = False
        except Exception as exc:
            self.failure_count += 1
            if self.max_failures > 0 and self.failure_count >= self.max_failures:
                self.heartbeat_unhealthy = True
                print(
                    "Trigger metadata heartbeat failed "
                    f"{self.failure_count} consecutive times; polling continues: {exc}"
                )
            else:
                print(f"Trigger metadata heartbeat failed: {exc}")

    async def _default_request(self, payload: dict) -> None:
        url = f"https://api.trigger.dev/api/v1/runs/{self.run_id}/metadata"
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=headers, json={"metadata": payload}) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise RuntimeError(f"metadata update failed: {response.status} {text}")
```

- [ ] **Шаг 7: Реализовать orchestration для daemon**

В тот же файл добавить:

```python
async def main() -> int:
    config = Config.from_env()
    if config.runtime_mode != "trigger-daemon":
        raise RuntimeError("padlbot.trigger_daemon requires PADL_RUNTIME_MODE=trigger-daemon")
    return await run_daemon(config)


async def run_daemon(config: Config) -> int:
    storage = Storage(config.db_path)
    storage.initialize()
    reporter = HeartbeatReporter(
        run_id=require_env("TRIGGER_RUN_ID"),
        secret_key=config.trigger_secret_key,
        generation=require_env("PADL_DAEMON_GENERATION", "unknown"),
        max_failures=config.heartbeat_max_failures,
    )

    async with OutdoorApiClient(
        config.site_base_url,
        timeout_seconds=config.request_timeout_seconds,
    ) as api:
        async with TelegramBot(config.telegram_bot_token) as bot:
            if config.delete_webhook_on_start:
                await bot.delete_webhook(
                    drop_pending_updates=config.drop_pending_updates_on_start,
                )

            manager = SearchManager(api=api, storage=storage, bot=bot, config=config)
            resumed_chat_ids = set(
                manager.resume_active_searches(storage.list_active_search_chat_ids())
            )
            if config.auto_start_search and config.admin_chat_id is not None and config.admin_chat_id not in resumed_chat_ids:
                preferences = storage.get_preferences(config.admin_chat_id)
                if config.default_venue_ids:
                    from dataclasses import replace

                    preferences = replace(preferences, venue_ids=config.default_venue_ids)
                    storage.save_preferences(config.admin_chat_id, preferences)
                response = await manager.start_search(config.admin_chat_id, preferences)
                await bot.send_message(config.admin_chat_id, response)

            heartbeat_task = asyncio.create_task(heartbeat_loop(reporter, manager, config))
            rotation_task = asyncio.create_task(asyncio.sleep(config.daemon_rotate_after_seconds))
            polling_task = asyncio.create_task(
                polling_loop(
                    bot=bot,
                    manager=manager,
                    storage=storage,
                    on_update_processed=lambda update_id: setattr(reporter, "last_update_id", update_id),
                    on_polling_error=lambda status, error: remember_polling_error(reporter, status, error),
                    conflict_exit_seconds=config.telegram_conflict_exit_seconds,
                )
            )
            done, pending = await asyncio.wait(
                {polling_task, rotation_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            polling_error = polling_task.exception() if polling_task in done else None
            if polling_error is not None:
                reporter.telegram_polling = "conflict" if is_telegram_conflict_error(polling_error) else "error"
                reporter.last_loop_error = str(polling_error)
            if rotation_task in done:
                await reporter.update(
                    status="rotating",
                    active_search_tasks=count_active_tasks(manager),
                    telegram_polling="stopping",
                )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            await manager.cancel_all_searches()
            await reporter.update(
                status="exiting",
                active_search_tasks=count_active_tasks(manager),
                telegram_polling=reporter.telegram_polling if polling_error is not None else "stopped",
                last_loop_error=reporter.last_loop_error,
                exit_reason=exit_reason_for(polling_error, rotation_task in done),
            )
            if polling_error is not None:
                raise polling_error
    return 0


async def heartbeat_loop(reporter: HeartbeatReporter, manager: SearchManager, config: Config) -> None:
    while True:
        await reporter.update(
            status="running",
            active_search_tasks=count_active_tasks(manager),
            telegram_polling="active",
        )
        await asyncio.sleep(config.heartbeat_seconds)


def count_active_tasks(manager: SearchManager) -> int:
    return sum(1 for task in manager.state.tasks.values() if not task.done())


def remember_polling_error(reporter: HeartbeatReporter, status: str, error: str) -> None:
    reporter.telegram_polling = status
    reporter.last_loop_error = error


def exit_reason_for(polling_error: BaseException | None, rotation_done: bool) -> str:
    if polling_error is not None:
        return "telegram-conflict" if is_telegram_conflict_error(polling_error) else "polling-error"
    return "planned-rotation" if rotation_done else "polling-exit"


def require_env(name: str, default: str | None = None) -> str:
    import os

    value = os.environ.get(name, default)
    if value is None or value == "":
        raise RuntimeError(f"{name} is required")
    return value
```

- [ ] **Шаг 8: Запустить тесты daemon и проверить GREEN**

Запустить:

```powershell
python -m unittest tests.test_trigger_daemon_wrapper tests.test_trigger_daemon -v
```

Ожидаемый результат: PASS.

- [ ] **Шаг 9: Закоммитить entrypoint daemon**

```powershell
git add src/__init__.py src/trigger/__init__.py src/trigger/run_padl_bot.py padlbot/trigger_daemon.py tests/test_trigger_daemon.py tests/test_trigger_daemon_wrapper.py
git commit -m "feat: add python trigger daemon entrypoint"
```

### Задача 9: Guard для отключения SMS в локальном entrypoint

**Файлы:**
- Изменить: `padlbot/__main__.py`
- Изменить: `tests/test_trigger_daemon.py`

- [ ] **Шаг 1: Добавить падающий тест для SMS disable guard**

Вставить этот класс в `tests/test_trigger_daemon.py` перед `if __name__ == "__main__":`:

```python
class LocalMainSmsGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_disable_sms_webhook_skips_local_webhook_start(self):
        from padlbot.__main__ import main as local_main

        config = Config(
            telegram_bot_token="token",
            sms_forward_secret="",
            disable_sms_webhook=True,
            auto_start_search=False,
        )

        class StopPolling(Exception):
            pass

        with patch("padlbot.__main__.Storage") as storage_cls, patch(
            "padlbot.__main__.OutdoorApiClient"
        ) as api_cls, patch("padlbot.__main__.TelegramBot") as bot_cls, patch(
            "padlbot.__main__.SearchManager"
        ) as manager_cls, patch("padlbot.__main__.start_sms_webhook", new=AsyncMock()) as sms, patch(
            "padlbot.__main__.polling_loop", new=AsyncMock(side_effect=StopPolling)
        ):
            storage_cls.return_value.list_active_search_chat_ids.return_value = []
            api_cls.return_value.__aenter__.return_value = object()
            api_cls.return_value.__aexit__.return_value = None
            bot_cls.return_value.__aenter__.return_value = object()
            bot_cls.return_value.__aexit__.return_value = None
            manager_cls.return_value.resume_active_searches.return_value = []

            with self.assertRaises(StopPolling):
                await local_main(config)

        sms.assert_not_called()
```

- [ ] **Шаг 2: Запустить тест и проверить RED**

Запустить:

```powershell
python -m unittest tests.test_trigger_daemon.LocalMainSmsGuardTests -v
```

Ожидаемый результат: FAIL, потому что `padlbot.__main__.main` всегда запускает SMS webhook.

- [ ] **Шаг 3: Добавить guard для SMS webhook в local main**

В `padlbot/__main__.py` заменить:

```python
            webhook_runner = await start_sms_webhook(manager, config)
```

на:

```python
            webhook_runner = None
            if not config.disable_sms_webhook and config.runtime_mode != "trigger-daemon":
                webhook_runner = await start_sms_webhook(manager, config)
```

Заменить cleanup:

```python
                await webhook_runner.cleanup()
```

на:

```python
                if webhook_runner is not None:
                    await webhook_runner.cleanup()
```

- [ ] **Шаг 4: Запустить сфокусированный тест и проверить GREEN**

Запустить:

```powershell
python -m unittest tests.test_trigger_daemon.LocalMainSmsGuardTests -v
```

Ожидаемый результат: PASS.

- [ ] **Шаг 5: Закоммитить guard для local entrypoint**

```powershell
git add padlbot/__main__.py tests/test_trigger_daemon.py
git commit -m "fix: allow disabling sms webhook"
```

### Задача 10: Документация и контракт окружения

**Файлы:**
- Изменить: `.env.example`
- Изменить: `README.md`
- Изменить: `README_RU.md`

- [ ] **Шаг 1: Обновить `.env.example`**

Заменить `.env.example` на:

```dotenv
TELEGRAM_BOT_TOKEN=123456:replace-me
ADMIN_CHAT_ID=
PADL_DB_PATH=data/padlbot.db
PADL_SITE_BASE_URL=https://api.outdoor.sport.mos.ru
REQUEST_TIMEOUT_SECONDS=15

AUTO_START_SEARCH=0
PADL_DEFAULT_VENUE_IDS=12,14,15

SMS_FORWARD_SECRET=
SMS_WEBHOOK_HOST=0.0.0.0
SMS_WEBHOOK_PORT=8080
PADL_DISABLE_SMS_WEBHOOK=0

TRIGGER_SECRET_KEY=tr_dev_replace-me
PADL_DAEMON_ENABLED=1
PADL_DAEMON_STOP_WHEN_DISABLED=0
PADL_RUNTIME_MODE=local
PADL_DELETE_WEBHOOK_ON_START=0
PADL_DROP_PENDING_UPDATES_ON_START=0
PADL_HEARTBEAT_SECONDS=30
PADL_HEARTBEAT_MAX_FAILURES=10
PADL_HEARTBEAT_STALE_SECONDS=180
PADL_HEARTBEAT_CANCEL_AFTER_SECONDS=300
PADL_START_GRACE_SECONDS=180
PADL_DAEMON_ROTATE_AFTER_SECONDS=82800
DAEMON_MAX_DURATION_SECONDS=86400
PADL_TELEGRAM_CONFLICT_EXIT_SECONDS=120
```

- [ ] **Шаг 2: Добавить раздел Trigger.dev в `README_RU.md`**

Добавить после раздела локальной настройки:

````markdown
## Демон в Trigger.dev Production

Облачный режим запускает бота как демон долгого опроса в Trigger.dev без Supabase и без публичного Telegram webhook.

Переменные окружения для Production:

```text
TELEGRAM_BOT_TOKEN=...
TRIGGER_SECRET_KEY=...
PADL_DAEMON_ENABLED=1
ADMIN_CHAT_ID=...
AUTO_START_SEARCH=1
PADL_DEFAULT_VENUE_IDS=12,14,15
PADL_SITE_BASE_URL=https://api.outdoor.sport.mos.ru
REQUEST_TIMEOUT_SECONDS=15
PADL_RUNTIME_MODE=trigger-daemon
PADL_DISABLE_SMS_WEBHOOK=1
PADL_DELETE_WEBHOOK_ON_START=1
PADL_DROP_PENDING_UPDATES_ON_START=0
```

Деплой:

```powershell
npm run trigger:dry-run
npm run trigger:deploy
```

После deploy запланированная task `padl-bot-ensure-daemon` раз в минуту проверяет активные runs `padl-bot-daemon`. Если демон отсутствует, завершился или heartbeat устарел после порога отмены, ensure-run запускает новый демон. Если metadata недоступна, ensure-run не запускает второй процесс polling в этот тик.

SQLite в Trigger Cloud считается состоянием best-effort. Если filesystem пережил restart, бот использует сохраненные preferences, search state, notified slots и Telegram offset. Если filesystem потерян, автоматически восстанавливается только мониторинг для `ADMIN_CHAT_ID` с `PADL_DEFAULT_VENUE_IDS`.

Аварийная остановка:

```text
PADL_DAEMON_ENABLED=0
PADL_DAEMON_STOP_WHEN_DISABLED=1
```

Не держите локальный `python -m padlbot` одновременно с Trigger daemon: два long polling процесса конфликтуют с Telegram `getUpdates`.
````

- [ ] **Шаг 3: Добавить раздел Trigger.dev в `README.md`**

Добавить короткий раздел на русском:

````markdown
## Демон в Trigger.dev Production

Production может работать как демон долгого опроса в Trigger.dev без Supabase и без публичного Telegram webhook. Деплой:

```powershell
npm run trigger:dry-run
npm run trigger:deploy
```

Запланированная task `padl-bot-ensure-daemon` раз в минуту проверяет активные runs `padl-bot-daemon` и запускает новый демон, если healthy run отсутствует. SQLite state в Trigger Cloud является best-effort: preferences, notified slots и Telegram offset сохраняются только если сохранился filesystem run. При пустом filesystem восстанавливается только admin monitoring из `ADMIN_CHAT_ID`, `AUTO_START_SEARCH=1` и `PADL_DEFAULT_VENUE_IDS`.

Для аварийной остановки установить `PADL_DAEMON_ENABLED=0` и `PADL_DAEMON_STOP_WHEN_DISABLED=1`. Не запускать локальный `python -m padlbot`, пока Trigger daemon выполняет Telegram polling.
````

- [ ] **Шаг 4: Запустить smoke-проверки документации**

Запустить:

```powershell
rg "Supabase" README.md README_RU.md docs/superpowers/plans/2026-07-02-padl-bot-trigger-only-self-healing-daemon.md
rg "PADL_DAEMON_ENABLED|PADL_RUNTIME_MODE|PADL_DISABLE_SMS_WEBHOOK" .env.example README.md README_RU.md
```

Ожидаемый результат: README упоминает Supabase только в контексте того, что Trigger daemon его не использует; env-ключи присутствуют в `.env.example` и документации.

- [ ] **Шаг 5: Закоммитить документацию**

```powershell
git add .env.example README.md README_RU.md
git commit -m "docs: document trigger daemon deployment"
```

### Задача 11: Проверка и deploy

**Файлы:**
- Проверить: весь репозиторий

- [ ] **Шаг 1: Запустить Python unit tests**

Запустить:

```powershell
python -m unittest discover -v
```

Ожидаемый результат: PASS.

- [ ] **Шаг 2: Запустить TypeScript unit tests**

Запустить:

```powershell
npm run test:trigger
```

Ожидаемый результат: PASS.

- [ ] **Шаг 3: Запустить Trigger dry-run**

Запустить:

```powershell
npm run trigger:dry-run
```

Ожидаемый результат: dry-run проходит успешно и включает `padl-bot-daemon`, `padl-bot-ensure-daemon`, `padlbot/**/*.py`, `src/trigger/**/*.py` и `requirements.txt` в build.

- [ ] **Шаг 4: Выполнить deploy**

Запустить:

```powershell
npm run trigger:deploy
```

Ожидаемый результат: deploy успешно проходит в Trigger.dev Production для проекта `proj_idvrbofrajznnafltimb`.

- [ ] **Шаг 5: Ручные production-проверки**

Проверить:

```text
1. Trigger Dashboard shows scheduled task padl-bot-ensure-daemon.
2. Within one minute, an EXECUTING padl-bot-daemon run appears.
3. runs.retrieve for the daemon run shows metadata.heartbeatAt.
4. Telegram /start returns the help message.
5. Telegram /search starts monitoring.
6. Telegram /status shows active monitoring.
7. Canceling the daemon run causes the next ensure run to start a replacement.
8. PADL_DAEMON_ENABLED=0 prevents restart.
9. PADL_DAEMON_ENABLED=0 and PADL_DAEMON_STOP_WHEN_DISABLED=1 cancels an active daemon.
10. A temporary metadata retrieve failure does not create a second daemon.
```

- [ ] **Шаг 6: Закоммитить заметки проверки, если изменилась документация**

Если ручной deploy выявит исправления документации, закоммитить их:

```powershell
git add README.md README_RU.md .env.example
git commit -m "docs: refine trigger daemon runbook"
```

## Самопроверка

- Покрытие спецификации: Trigger packaging, task-level `maxDuration`, retry `maxAttempts=1`, декларативный cron `schedules.task`, active statuses SDK 4.4.6 без `WAITING`, `REATTEMPTING` или `FROZEN`, metadata policy через `runs.retrieve`, fail-closed поведение для unknown, Python daemon wrapper, SMS-disabled cloud mode, heartbeat metadata в формате `{ "metadata": ... }`, плановая ротация, выход при Telegram 409 conflict, best-effort state в SQLite, Telegram offset ordering, kill switch, docs и deploy checks сопоставлены с задачами выше.
- Проверка placeholder: запрещенных маркеров нет; шаги с изменением кода содержат конкретные фрагменты, команды и ожидаемые результаты.
- Согласованность типов: TypeScript ids используют `padl-bot-daemon` и `padl-bot-ensure-daemon`; имена Python config совпадают с env keys из спецификации; storage methods: `get_last_update_id`, `save_last_update_id` и `mark_slot_notified`; daemon runtime mode везде `trigger-daemon`.
