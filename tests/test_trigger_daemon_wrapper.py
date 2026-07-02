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
