"""Дашборд (PR-19): расход токенов по моделям/дням и новые admin-роуты
(/admin/api/tokens, /admin/api/queue, /admin/api/gift) требуют валидной
сессии так же строго, как уже существующие /admin/api/*."""
from __future__ import annotations

import os
import tempfile

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.api.server import build_app
from bot.config import settings
from bot.db.database import get_db, init_db
from bot.db.queries import get_token_usage, upsert_user


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


async def _insert_llm_call(user_id: int, model: str, tokens_in: int, tokens_out: int) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO events(user_id, type, model, tokens_in, tokens_out) "
            "VALUES(?, 'llm_call', ?, ?, ?);",
            (user_id, model, tokens_in, tokens_out),
        )
        await db.commit()


# ───────────────────────── get_token_usage ─────────────────────────

async def test_token_usage_aggregates_by_model_and_day(temp_db) -> None:
    await _insert_llm_call(1, "GigaChat-2-Pro", 100, 50)
    await _insert_llm_call(1, "GigaChat-2-Pro", 200, 80)
    await _insert_llm_call(2, "GigaChat-3-Ultra", 300, 120)

    rows = await get_token_usage(30)
    by_model = {r["model"]: r for r in rows}

    assert by_model["GigaChat-2-Pro"]["calls"] == 2
    assert by_model["GigaChat-2-Pro"]["tokens_in"] == 300
    assert by_model["GigaChat-2-Pro"]["tokens_out"] == 130
    assert by_model["GigaChat-3-Ultra"]["calls"] == 1


async def test_token_usage_ignores_non_llm_events(temp_db) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO events(user_id, type, duration_sec) VALUES(1, 'recognize', 60);"
        )
        await db.commit()
    assert await get_token_usage(30) == []


async def test_token_usage_empty_when_no_calls(temp_db) -> None:
    assert await get_token_usage(30) == []


# ───────────────────────── admin API auth ─────────────────────────

@pytest.fixture
async def client(temp_db):
    async with TestClient(TestServer(build_app())) as c:
        yield c


async def test_admin_tokens_requires_session(client) -> None:
    resp = await client.get("/admin/api/tokens")
    assert resp.status == 401


async def test_admin_queue_requires_session(client) -> None:
    resp = await client.get("/admin/api/queue")
    assert resp.status == 401


async def test_admin_gift_requires_session(client) -> None:
    resp = await client.post("/admin/api/gift", json={"tg_id": 1, "minutes": 10})
    assert resp.status == 401


async def test_admin_queue_reports_three_lanes_when_authenticated(client, monkeypatch) -> None:
    monkeypatch.setattr("bot.api.server._valid_session", lambda request: True)
    resp = await client.get("/admin/api/queue")
    assert resp.status == 200
    data = await resp.json()
    assert set(data.keys()) == {"llm", "stt", "ffmpeg"}


async def test_admin_gift_rejects_non_positive_minutes(client, monkeypatch) -> None:
    monkeypatch.setattr("bot.api.server._valid_session", lambda request: True)
    resp = await client.post("/admin/api/gift", json={"tg_id": 1, "minutes": 0})
    assert resp.status == 400


async def test_admin_gift_404_for_unknown_user(client, monkeypatch) -> None:
    monkeypatch.setattr("bot.api.server._valid_session", lambda request: True)
    resp = await client.post("/admin/api/gift", json={"tg_id": 999999, "minutes": 5})
    assert resp.status == 404


async def test_admin_gift_credits_existing_user(client, monkeypatch) -> None:
    await upsert_user(user_id=42, username="u", first_name="U")
    monkeypatch.setattr("bot.api.server._valid_session", lambda request: True)

    resp = await client.post("/admin/api/gift", json={"tg_id": 42, "minutes": 15})

    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
