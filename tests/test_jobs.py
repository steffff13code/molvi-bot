"""jobs / надёжность-2 (PR-20): рестарт Railway посреди STT не должен оставлять
пользователя молча смотреть на «⏳» — create_job/finish_job фиксируют рисковое
окно, get_stalled_jobs находит осиротевшие записи, notify_stalled_jobs шлёт
уведомление и закрывает их терминально (иначе слать будем при каждом рестарте)."""
from __future__ import annotations

import os
import tempfile

import pytest

from bot.config import settings
from bot.db.database import init_db
from bot.db.queries import create_job, finish_job, get_stalled_jobs
from bot.services.jobs_recovery import notify_stalled_jobs


@pytest.fixture
async def temp_db():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    os.remove(path)
    original = settings.db_path
    object.__setattr__(settings, "db_path", path)
    await init_db()
    try:
        yield path
    finally:
        object.__setattr__(settings, "db_path", original)
        for p in (path, path + "-wal", path + "-shm"):
            if os.path.exists(p):
                os.remove(p)


class _FakeBot:
    def __init__(self, fail_for: set[int] | None = None) -> None:
        self.sent: list[tuple[int, str]] = []
        self._fail_for = fail_for or set()

    async def send_message(self, chat_id: int, text: str) -> None:
        if chat_id in self._fail_for:
            raise RuntimeError("bot was blocked")
        self.sent.append((chat_id, text))


async def test_create_job_starts_in_processing_state(temp_db) -> None:
    job_id = await create_job(1, kind="recognize")
    stalled = await get_stalled_jobs()
    assert [j["id"] for j in stalled] == [job_id]
    assert stalled[0]["user_id"] == 1
    assert stalled[0]["kind"] == "recognize"


async def test_finish_job_removes_it_from_stalled(temp_db) -> None:
    job_id = await create_job(1, kind="recognize")
    await finish_job(job_id, "done")
    assert await get_stalled_jobs() == []


async def test_finish_job_failed_also_removes_it_from_stalled(temp_db) -> None:
    job_id = await create_job(1, kind="recognize")
    await finish_job(job_id, "failed")
    assert await get_stalled_jobs() == []


async def test_get_stalled_jobs_only_returns_processing(temp_db) -> None:
    done_job = await create_job(1, kind="recognize")
    await finish_job(done_job, "done")
    stuck_job = await create_job(2, kind="recognize")

    stalled = await get_stalled_jobs()

    assert [j["id"] for j in stalled] == [stuck_job]


async def test_notify_stalled_jobs_sends_message_and_closes_job(temp_db) -> None:
    await create_job(42, kind="recognize")
    bot = _FakeBot()

    await notify_stalled_jobs(bot)

    assert bot.sent[0][0] == 42
    assert "Мои записи" in bot.sent[0][1]
    assert await get_stalled_jobs() == []


async def test_notify_stalled_jobs_closes_job_even_if_send_fails(temp_db) -> None:
    await create_job(99, kind="recognize")
    bot = _FakeBot(fail_for={99})

    await notify_stalled_jobs(bot)  # не должно бросить исключение

    assert await get_stalled_jobs() == []


async def test_notify_stalled_jobs_noop_when_nothing_stalled(temp_db) -> None:
    bot = _FakeBot()
    await notify_stalled_jobs(bot)
    assert bot.sent == []
