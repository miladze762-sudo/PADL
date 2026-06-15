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

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Config":
        file_values = load_env_file(env_file)
        merged: Mapping[str, str] = {**file_values, **os.environ}
        token = merged.get("TELEGRAM_BOT_TOKEN", "").strip()
        secret = merged.get("SMS_FORWARD_SECRET", "").strip()
        if not token:
            raise ConfigError("TELEGRAM_BOT_TOKEN is required")
        return cls(
            telegram_bot_token=token,
            sms_forward_secret=secret,
            admin_chat_id=_int_value(merged.get("ADMIN_CHAT_ID")),
            db_path=Path(merged.get("PADL_DB_PATH", "data/padlbot.db")),
            site_base_url=merged.get(
                "PADL_SITE_BASE_URL", "https://api.outdoor.sport.mos.ru"
            ).rstrip("/"),
            sms_host=merged.get("SMS_WEBHOOK_HOST", "0.0.0.0"),
            sms_port=int(merged.get("SMS_WEBHOOK_PORT", "8080")),
            lock_host=merged.get("PADL_LOCK_HOST", "127.0.0.1"),
            lock_port=int(merged.get("PADL_LOCK_PORT", "8765")),
            dry_run=_bool_value(merged.get("PADL_DRY_RUN"), default=False),
            auto_start_search=_bool_value(merged.get("AUTO_START_SEARCH"), default=False),
            request_timeout_seconds=float(merged.get("REQUEST_TIMEOUT_SECONDS", "15")),
        )
