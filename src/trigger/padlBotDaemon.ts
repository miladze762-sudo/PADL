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
