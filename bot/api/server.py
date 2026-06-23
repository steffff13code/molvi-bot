"""Маленький HTTP-API внутри процесса бота (для админки на reg.ru).

Поднимается на 0.0.0.0:$PORT параллельно polling. Все /api/* защищены
заголовком X-Admin-Token (== ADMIN_API_TOKEN). Отдаёт ТОЛЬКО агрегаты и
управление whitelist — никакого контента пользователей (Вариант А).
"""

from __future__ import annotations

from aiohttp import web
from loguru import logger

from bot.config import settings
from bot.db.queries import (
    get_stats,
    whitelist_add,
    whitelist_list,
    whitelist_remove,
)


def _check_token(request: web.Request) -> bool:
    token = settings.admin_api_token
    if not token:
        return False
    return request.headers.get("X-Admin-Token") == token


@web.middleware
async def _auth_mw(request: web.Request, handler):
    if request.path.startswith("/api/"):
        if not settings.admin_api_token:
            return web.json_response({"error": "API disabled (no ADMIN_API_TOKEN)"}, status=503)
        if not _check_token(request):
            return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def _health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "molvi-bot"})


async def _stats(request: web.Request) -> web.Response:
    try:
        days = int(request.query.get("days", "30"))
    except ValueError:
        days = 30
    days = max(1, min(days, 365))
    return web.json_response(await get_stats(days))


async def _wl_list(request: web.Request) -> web.Response:
    return web.json_response({"items": await whitelist_list()})


async def _wl_add(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        body = {}
    tg_id = body.get("tg_id")
    username = body.get("username")
    note = body.get("note")
    try:
        tg_id = int(tg_id) if tg_id not in (None, "") else None
    except (TypeError, ValueError):
        tg_id = None
    ok = await whitelist_add(tg_id=tg_id, username=username, note=note)
    return web.json_response({"ok": ok}, status=200 if ok else 400)


async def _wl_remove(request: web.Request) -> web.Response:
    try:
        entry_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"ok": False, "error": "bad id"}, status=400)
    ok = await whitelist_remove(entry_id)
    return web.json_response({"ok": ok}, status=200 if ok else 404)


def build_app() -> web.Application:
    app = web.Application(middlewares=[_auth_mw])
    app.router.add_get("/health", _health)
    app.router.add_get("/api/stats", _stats)
    app.router.add_get("/api/whitelist", _wl_list)
    app.router.add_post("/api/whitelist", _wl_add)
    app.router.add_delete("/api/whitelist/{id}", _wl_remove)
    return app


async def start_api(port: int) -> None:
    """Запускает API в текущем event loop (не блокирует)."""
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("API listening on 0.0.0.0:{port}", port=port)
