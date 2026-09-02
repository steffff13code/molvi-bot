"""Живость polling для честного /health: /health раньше отдавал 200 безусловно
(bot/api/server.py), не проверяя ни БД, ни то, жив ли вообще polling — внешний
монитор был бы зелёным на мёртвом боте.

HeartbeatMiddleware отмечает МОМЕНТ ПОЛУЧЕНИЯ апдейта от Telegram (не факт успешной
обработки хендлером — за баг в одном хендлере отвечает @dp.errors() в bot/main.py,
а не healthcheck). _hb_loop раз в HEARTBEAT_INTERVAL_SEC пингует settings.heartbeat_url,
но только пока polling жив — безусловный пинг остановку polling не поймает и создаст
ложное спокойствие.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import TelegramObject
from loguru import logger

from bot.config import settings

HEARTBEAT_INTERVAL_SEC = 300
STALE_AFTER_SEC = 300

_start_at = time.monotonic()
_last_update_at = time.monotonic()


def age_sec() -> float:
    """Секунд с последнего полученного polling-апдейта."""
    return time.monotonic() - _last_update_at


def uptime() -> float:
    return time.monotonic() - _start_at


def is_alive() -> bool:
    return age_sec() < STALE_AFTER_SEC


class HeartbeatMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        global _last_update_at
        _last_update_at = time.monotonic()
        return await handler(event, data)


async def _hb_loop() -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
        if not settings.heartbeat_url or not is_alive():
            continue
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.get(settings.heartbeat_url)
        except Exception as e:
            logger.warning("Heartbeat ping failed: {e}", e=e)


def start(dp: Dispatcher) -> None:
    """Регистрирует middleware на диспетчере и запускает фоновый пинг-цикл."""
    dp.update.outer_middleware(HeartbeatMiddleware())
    asyncio.create_task(_hb_loop())
