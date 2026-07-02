from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigError(RuntimeError):
    pass


def load_env_file(path: str | Path = ".env") -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _bool_value(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_value(value: str | None, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    return int(value)


def _list_int_value(value: str | None) -> tuple[int, ...]:
    if value is None or value.strip() == "":
        return ()
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    sms_forward_secret: str
    admin_chat_id: int | None = None
    db_path: Path = Path("data/padlbot.db")
    site_base_url: str = "https://api.outdoor.sport.mos.ru"
    sms_host: str = "0.0.0.0"
    sms_port: int = 8080
    lock_host: str = "127.0.0.1"
    lock_port: int = 8765
    dry_run: bool = False
    auto_start_search: bool = False
    request_timeout_seconds: float = 15.0
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

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Config":
        file_values = load_env_file(env_file)
        merged: Mapping[str, str] = {**file_values, **os.environ}
        token = merged.get("TELEGRAM_BOT_TOKEN", "").strip()
        secret = merged.get("SMS_FORWARD_SECRET", "").strip()
        if not token:
            raise ConfigError("TELEGRAM_BOT_TOKEN is required")
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

        return cls(
            telegram_bot_token=token,
            sms_forward_secret=secret,
            admin_chat_id=admin_chat_id,
            db_path=Path(merged.get("PADL_DB_PATH", "data/padlbot.db")),
            site_base_url=merged.get(
                "PADL_SITE_BASE_URL", "https://api.outdoor.sport.mos.ru"
            ).rstrip("/"),
            sms_host=merged.get("SMS_WEBHOOK_HOST", "0.0.0.0"),
            sms_port=int(merged.get("SMS_WEBHOOK_PORT", "8080")),
            lock_host=merged.get("PADL_LOCK_HOST", "127.0.0.1"),
            lock_port=int(merged.get("PADL_LOCK_PORT", "8765")),
            dry_run=_bool_value(merged.get("PADL_DRY_RUN"), default=False),
            auto_start_search=auto_start_search,
            request_timeout_seconds=float(merged.get("REQUEST_TIMEOUT_SECONDS", "15")),
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
        )
