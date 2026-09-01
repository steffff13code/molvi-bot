"""Lane — дисциплина очереди для провайдеров с ограниченным числом потоков (PR-6):
GigaChat даёт физлицу ровно один поток вне зависимости от оплаты."""
from __future__ import annotations

import asyncio

from bot.services.concurrency import Lane


async def test_three_concurrent_calls_succeed_with_one_permit() -> None:
    lane = Lane("test", permits=1, seed_sec=0.01)
    completed: list[int] = []

    async def work(i: int) -> int:
        await asyncio.sleep(0.01)
        completed.append(i)
        return i

    results = await asyncio.gather(*(lane.run(lambda i=i: work(i)) for i in range(3)))

    assert sorted(results) == [0, 1, 2]
    assert len(completed) == 3  # ноль потерянных/провалившихся вызовов


async def test_run_serializes_calls_under_single_permit() -> None:
    lane = Lane("test", permits=1, seed_sec=0.01)
    concurrent_now = 0
    max_concurrent = 0

    async def work() -> None:
        nonlocal concurrent_now, max_concurrent
        concurrent_now += 1
        max_concurrent = max(max_concurrent, concurrent_now)
        await asyncio.sleep(0.01)
        concurrent_now -= 1

    await asyncio.gather(*(lane.run(work) for _ in range(3)))

    assert max_concurrent == 1  # ни разу не было двух одновременных выполнений


async def test_eta_sec_grows_with_depth() -> None:
    lane = Lane("test", permits=1, seed_sec=2.0)
    assert lane.eta_sec() == 0.0

    lane._waiting = 1
    eta_at_1 = lane.eta_sec()
    lane._waiting = 3
    eta_at_3 = lane.eta_sec()

    assert eta_at_3 > eta_at_1 > 0.0


async def test_on_wait_fires_with_position_and_on_start_fires_on_acquire() -> None:
    lane = Lane("test", permits=1, seed_sec=0.05)
    release = asyncio.Event()

    async def holder() -> None:
        await release.wait()

    holder_task = asyncio.create_task(lane.run(holder))
    await asyncio.sleep(0.01)  # держатель точно захватил единственное разрешение

    seen_wait: list[tuple[int, float]] = []
    started = asyncio.Event()

    async def on_wait(position: int, eta: float) -> None:
        seen_wait.append((position, eta))

    async def on_start() -> None:
        started.set()

    async def waiter() -> None:
        await lane.run(lambda: asyncio.sleep(0), on_wait=on_wait, on_start=on_start)

    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)

    assert len(seen_wait) == 1
    assert seen_wait[0][0] == 1  # позиция в очереди
    assert not started.is_set()  # разрешение ещё не получено — держатель не отпустил

    release.set()
    await asyncio.gather(holder_task, waiter_task)

    assert started.is_set()  # on_start сработал при получении разрешения


async def test_on_wait_not_called_when_permit_free() -> None:
    lane = Lane("test", permits=2, seed_sec=0.01)
    called = False

    async def on_wait(position: int, eta: float) -> None:
        nonlocal called
        called = True

    await lane.run(lambda: asyncio.sleep(0), on_wait=on_wait)

    assert not called
