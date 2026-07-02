import os
import unittest
from pathlib import Path
from unittest.mock import patch

from padlbot.config import Config


class ConfigTests(unittest.TestCase):
    def test_sms_forward_secret_is_optional_for_monitoring(self):
        env_path = Path.cwd() / ".tmp" / "test-config.env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            env_path.write_text("TELEGRAM_BOT_TOKEN=token\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                config = Config.from_env(env_path)
        finally:
            env_path.unlink(missing_ok=True)

        self.assertEqual(config.telegram_bot_token, "token")
        self.assertEqual(config.sms_forward_secret, "")

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


if __name__ == "__main__":
    unittest.main()
