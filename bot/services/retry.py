from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
from loguru import logger

T = TypeVar("T")


class NonRetryable(Exception):
    """Ошибка, которую повторять бессмысленно: результат будет тот же."""


# Коды, на которых повтор заведомо не поможет (клиентская ошибка / квота /
# файл слишком большой) — незачем оплачивать вызов провайдера трижды подряд.
NON_RETRYABLE_STATUS = {400, 401, 402, 403, 404, 413, 415, 422}


async def with_retries(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.8,
    max_delay: float = 30.0,
    total_budget: float = 240.0,
    op: str = "",
) -> T:
    """Повторяет только то, что имеет шанс сработать со второго раза.

    Не повторяет: NonRetryable, httpx.HTTPStatusError с кодом из
    NON_RETRYABLE_STATUS, asyncio.CancelledError (пробрасывается наверх
    немедленно). Джиттер ±50% от расчётной паузы, общий бюджет времени —
    как только очередная пауза вышла бы за total_budget, повтор не делается.
    """
    start = time.monotonic()
    last_exc: Exception | None = None

    for i in range(attempts):
        try:
            return await fn()
        except asyncio.CancelledError:
            raise
        except NonRetryable:
            raise
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code in NON_RETRYABLE_STATUS:
                raise
            last_exc = e
        except Exception as e:
            last_exc = e

        if i == attempts - 1:
            break

        delay = min(base_delay * (2**i), max_delay)
        delay *= random.uniform(0.5, 1.5)
        if time.monotonic() - start + delay >= total_budget:
            break

        logger.warning(
            "Retry {i}/{n} for {op} after error: {e}",
            i=i + 1, n=attempts, op=op or "?", e=last_exc,
        )
        await asyncio.sleep(delay)

    assert last_exc is not None
    raise last_exc
