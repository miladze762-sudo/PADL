from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from padlbot.config import ConfigError, load_env_file
from padlbot.models import SearchPreferences
from padlbot.outdoor_api import OutdoorApiClient
from padlbot.scanner import SlotScanner
from padlbot.formatting import format_slot


async def main() -> None:
    env = load_env_file()
    base_url = env.get("PADL_SITE_BASE_URL", "https://api.outdoor.sport.mos.ru")
    preferences = SearchPreferences()
    async with OutdoorApiClient(base_url) as api:
        slot = await SlotScanner(api).find_best_slot(preferences)
    if slot is None:
        print("No matching slot found.")
        return
    print(format_slot(slot, preferences.tickets_count))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConfigError as exc:
        print(exc)
