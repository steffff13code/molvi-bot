from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from loguru import logger


T = TypeVar("T")


async def with_retries(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.8,
) -> T:
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return await fn()
        except Exception as e:
            last_exc = e
            if i == attempts - 1:
                break
            delay = base_delay * (2**i)
            logger.warning("Retry {i}/{n} after error: {e}", i=i + 1, n=attempts, e=e)
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc

