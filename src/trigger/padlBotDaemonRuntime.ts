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
    const createdAgeSeconds = secondsBetween(run.createdAt, options.now);
    if (createdAgeSeconds < options.startGraceSeconds) {
      return { kind: "starting", run, ageSeconds: createdAgeSeconds };
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
