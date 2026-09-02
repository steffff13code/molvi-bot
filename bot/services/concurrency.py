"""Дисциплина очереди для провайдеров с ограниченным числом параллельных потоков.

У физлица GigaChat даёт ровно один поток вне зависимости от оплаты — без семафора
второй одновременный пользователь получает ошибку 429 вместо места в очереди.
Lane даёт: (а) семафор на N параллельных вызовов, (б) скользящее среднее времени
обслуживания, чтобы оценить ожидание для тех, кто в очереди, (в) колбэк on_wait,
чтобы показать пользователю реальную оценку вместо голой ошибки.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from bot.config import settings

T = TypeVar("T")

_EMA_ALPHA = 0.3  # вес нового замера в скользящем среднем времени обслуживания


class LaneTimeout(Exception):
    """Не удалось получить разрешение за wait_timeout секунд."""


class Lane:
    def __init__(self, name: str, permits: int, seed_sec: float) -> None:
        self.name = name
        self._sem = asyncio.Semaphore(permits)
        self._avg_sec = seed_sec
        self._waiting = 0

    @property
    def depth(self) -> int:
        """Сколько ждут разрешения прямо сейчас (не считая того, кто уже внутри)."""
        return self._waiting

    def eta_sec(self) -> float:
        """Грубая оценка ожидания: глубина очереди × среднее время обслуживания."""
        return self._waiting * self._avg_sec

    async def run(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        wait_timeout: float = 280.0,
        on_wait: Callable[[int, float], Awaitable[None]] | None = None,
        on_start: Callable[[], Awaitable[None]] | None = None,
    ) -> T:
        """Выполняет fn под семафором. on_wait(position, eta) вызывается один раз,
        если разрешение не получено мгновенно; on_start() — когда разрешение
        получено (только если до этого был on_wait, т.е. реально ждали).
        """
        would_wait = self._sem.locked()
        if would_wait:
            self._waiting += 1
            position = self._waiting
            if on_wait is not None:
                try:
                    await on_wait(position, self.eta_sec())
                except Exception:
                    pass

        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=wait_timeout)
        except asyncio.TimeoutError:
            if would_wait:
                self._waiting -= 1
            raise LaneTimeout(
                f"{self.name}: не удалось получить разрешение за {wait_timeout}с"
            ) from None

        if would_wait:
            self._waiting -= 1
            if on_start is not None:
                try:
                    await on_start()
                except Exception:
                    pass

        start = time.monotonic()
        try:
            return await fn()
        finally:
            elapsed = time.monotonic() - start
            self._avg_sec = self._avg_sec * (1 - _EMA_ALPHA) + elapsed * _EMA_ALPHA
            self._sem.release()


# gigachat_streams=1 — реальный лимит физлица; станет больше только вместе
# с переходом на тариф ИП, и это отдельное решение владельца.
LLM_LANE = Lane("llm", permits=settings.gigachat_streams, seed_sec=45)
STT_LANE = Lane("stt", permits=3, seed_sec=90)
FFMPEG_LANE = Lane("ffmpeg", permits=2, seed_sec=5)
