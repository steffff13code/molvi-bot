"""with_retries — повторяет только то, что имеет шанс сработать со второго раза (PR-6)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from bot.services.retry import NonRetryable, with_retries


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.invalid/")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError(str(code), request=request, response=response)


async def test_non_retryable_called_exactly_once() -> None:
    calls = 0

    async def fn() -> None:
        nonlocal calls
        calls += 1
        raise NonRetryable("бесполезно повторять")

    with pytest.raises(NonRetryable):
        await with_retries(fn, attempts=5, base_delay=0.001)
    assert calls == 1


async def test_http_402_not_retried() -> None:
    calls = 0

    async def fn() -> None:
        nonlocal calls
        calls += 1
        raise _status_error(402)

    with pytest.raises(httpx.HTTPStatusError):
        await with_retries(fn, attempts=5, base_delay=0.001)
    assert calls == 1


async def test_http_500_retried_up_to_attempts() -> None:
    calls = 0

    async def fn() -> None:
        nonlocal calls
        calls += 1
        raise _status_error(500)

    with pytest.raises(httpx.HTTPStatusError):
        await with_retries(fn, attempts=3, base_delay=0.001)
    assert calls == 3


async def test_cancelled_error_propagates_immediately() -> None:
    calls = 0

    async def fn() -> None:
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await with_retries(fn, attempts=5, base_delay=0.001)
    assert calls == 1


async def test_generic_error_retried_then_succeeds() -> None:
    calls = 0

    async def fn() -> str:
        nonlocal calls
        calls += 1
        if calls < 2:
            raise RuntimeError("transient")
        return "ok"

    result = await with_retries(fn, attempts=3, base_delay=0.001)
    assert result == "ok"
    assert calls == 2


async def test_total_budget_stops_further_retries() -> None:
    calls = 0

    async def fn() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("always fails")

    with pytest.raises(RuntimeError):
        await with_retries(fn, attempts=10, base_delay=1.0, total_budget=0.01)
    assert 1 <= calls < 10  # бюджет времени оборвал повторы раньше attempts
