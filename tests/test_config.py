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


if __name__ == "__main__":
    unittest.main()
