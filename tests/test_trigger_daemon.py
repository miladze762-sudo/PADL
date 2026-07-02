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
