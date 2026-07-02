from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "daemon"
    if command == "healthcheck":
        return 0
    if command != "daemon":
        print(f"Unknown command: {command}")
        return 2

    from padlbot.trigger_daemon import main as daemon_main

    return await daemon_main()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
