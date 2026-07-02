import { describe, expect, it } from "vitest";
import {
  ACTIVE_DAEMON_STATUSES,
  DAEMON_RETRY_MAX_ATTEMPTS,
  classifyDaemonRun,
  createDaemonTriggerRequest,
  parseSupervisorEnv,
  planSupervisorActions,
} from "./padlBotDaemonRuntime";
import { DAEMON_TASK_CONFIG, ENSURE_DAEMON_CRON } from "./padlBotDaemon";

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
