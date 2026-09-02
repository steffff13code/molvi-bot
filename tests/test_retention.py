"""Ретеншен records.transcript (PR-7): delete_old_records удаляет старое и не
трогает свежее; delete_record проверяет владельца; delete_user_records — /forget."""
from __future__ import annotations

import os
import tempfile

import pytest

from bot.config import settings
from bot.db.database import get_db, init_db
from bot.db.queries import delete_old_records, delete_record, delete_user_records


@pytest.fixture
async def temp_db():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    os.remove(path)  # соединение создаст файл заново
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


async def _insert_record(user_id: int, transcript: str, days_ago: int) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO records(user_id, transcript, duration_sec, created_at) "
            "VALUES(?, ?, ?, datetime('now', ?));",
            (user_id, transcript, 60, f"-{days_ago} days"),
        )
        await db.commit()
        return cur.lastrowid or 0


async def test_delete_old_records_removes_old_keeps_fresh(temp_db) -> None:
    old_id = await _insert_record(1, "старая запись", days_ago=40)
    fresh_id = await _insert_record(1, "свежая запись", days_ago=5)

    deleted = await delete_old_records(30)

    assert deleted == 1
    async with get_db() as db:
        cur = await db.execute("SELECT id FROM records;")
        remaining = {row["id"] for row in await cur.fetchall()}
    assert remaining == {fresh_id}
    assert old_id not in remaining


async def test_delete_old_records_noop_when_nothing_old(temp_db) -> None:
    await _insert_record(1, "свежая запись", days_ago=1)
    assert await delete_old_records(30) == 0


async def test_delete_user_records_removes_only_that_user(temp_db) -> None:
    await _insert_record(1, "запись пользователя 1", days_ago=1)
    await _insert_record(2, "запись пользователя 2", days_ago=1)

    deleted = await delete_user_records(1)

    assert deleted == 1
    async with get_db() as db:
        cur = await db.execute("SELECT user_id FROM records;")
        remaining = [row["user_id"] for row in await cur.fetchall()]
    assert remaining == [2]


async def test_delete_record_requires_matching_owner(temp_db) -> None:
    rec_id = await _insert_record(1, "чужая запись", days_ago=1)

    assert await delete_record(rec_id, user_id=2) is False
    assert await delete_record(rec_id, user_id=1) is True
    assert await delete_record(rec_id, user_id=1) is False  # уже удалена
