from __future__ import annotations

from .config import Config
from .selection import extract_sms_code

try:
    from aiohttp import web
except ImportError:  # pragma: no cover - exercised only before dependencies are installed.
    web = None


def _require_aiohttp() -> None:
    if web is None:
        raise RuntimeError("aiohttp is not installed. Run: pip install -r requirements.txt")


async def _request_data(request) -> dict:
    try:
        data = await request.json()
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    form = await request.post()
    return dict(form)


def create_sms_app(manager, config: Config):
    _require_aiohttp()
    app = web.Application()

    async def sms(request):
        data = await _request_data(request)
        if not config.sms_forward_secret or data.get("secret") != config.sms_forward_secret:
            return web.json_response({"ok": False, "error": "forbidden"}, status=403)

        text = str(data.get("text") or data.get("message") or data.get("body") or "")
        code = extract_sms_code(text)
        if code is None:
            return web.json_response({"ok": False, "error": "sms code not found"}, status=400)

        chat_id = data.get("chat_id") or config.admin_chat_id
        if chat_id is None:
            return web.json_response({"ok": False, "error": "chat_id is required"}, status=400)

        try:
            await manager.submit_sms_code(int(chat_id), code)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True})

    app.router.add_post("/sms", sms)
    return app


async def start_sms_webhook(manager, config: Config):
    _require_aiohttp()
    runner = web.AppRunner(create_sms_app(manager, config))
    await runner.setup()
    site = web.TCPSite(runner, config.sms_host, config.sms_port)
    await site.start()
    return runner
