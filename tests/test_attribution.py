"""Атрибуция источника (PR-13): парсер /start-payload не падает на мусоре от
пользователя, а upsert_user пишет источник строго first-touch — повторный
/start по новой рекламной ссылке не должен затирать реальный первоисточник."""
from __future__ import annotations

import os
import tempfile

import pytest

from bot.config import settings
from bot.db.database import get_db, init_db
from bot.db.queries import upsert_user
from bot.utils import parse_start_payload, source_label


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


# ───────────────────────── parse_start_payload ─────────────────────────

def test_empty_payload_returns_empty_dict() -> None:
    assert parse_start_payload(None) == {}
    assert parse_start_payload("") == {}


def test_payload_over_64_chars_rejected() -> None:
    assert parse_start_payload("a" * 65) == {}


def test_payload_at_64_chars_accepted() -> None:
    raw = "s_" + "y" * 62
    assert parse_start_payload(raw) == {"s": raw.split("_", 1)[1][:16]}


def test_script_tag_rejected() -> None:
    assert parse_start_payload("<script>alert(1)</script>") == {}


def test_cyrillic_rejected() -> None:
    assert parse_start_payload("источник_яндекс") == {}


def test_path_traversal_rejected() -> None:
    assert parse_start_payload("..%2F..%2Fetc") == {}


def test_valid_multi_key_payload() -> None:
    assert parse_start_payload("s_yd-m_cpc-c_brand") == {"s": "yd", "m": "cpc", "c": "brand"}


def test_bare_source_backward_compat() -> None:
    # /start promo — старый формат без ключей, весь payload = source.
    assert parse_start_payload("promo") == {"s": "promo"}


def test_unknown_keys_silently_dropped() -> None:
    assert parse_start_payload("s_yd-z_unknown") == {"s": "yd"}


def test_values_truncated_to_16_chars() -> None:
    long_val = "x" * 30
    assert parse_start_payload(f"s_{long_val}") == {"s": long_val[:16]}


def test_source_label_defaults() -> None:
    assert source_label({}) == "direct/none"
    assert source_label({"s": "yd", "m": "cpc"}) == "yd/cpc"


# ───────────────────────── upsert_user first-touch ─────────────────────────

async def _get_attribution(user_id: int) -> dict:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT source, campaign, start_payload, source_at FROM users WHERE user_id=?;",
            (user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else {}


async def test_first_start_records_source(temp_db) -> None:
    await upsert_user(user_id=1, username="u", first_name="U", payload="s_yd-m_cpc-c_brand")
    row = await _get_attribution(1)
    assert row["source"] == "yd"
    assert row["campaign"] == "brand"
    assert row["start_payload"] == "s_yd-m_cpc-c_brand"
    assert row["source_at"] is not None


async def test_repeat_start_does_not_overwrite_source(temp_db) -> None:
    await upsert_user(user_id=1, username="u", first_name="U", payload="s_yd-m_cpc-c_brand")
    await upsert_user(user_id=1, username="u", first_name="U", payload="s_tg-m_post-c_new")
    row = await _get_attribution(1)
    assert row["source"] == "yd"  # первый источник сохранён
    assert row["campaign"] == "brand"


async def test_plain_start_without_payload_leaves_source_null(temp_db) -> None:
    await upsert_user(user_id=1, username="u", first_name="U")
    row = await _get_attribution(1)
    assert row["source"] is None
    assert row["source_at"] is None


async def test_garbage_payload_does_not_crash_upsert(temp_db) -> None:
    await upsert_user(user_id=1, username="u", first_name="U", payload="<script>alert(1)</script>")
    row = await _get_attribution(1)
    # мусор не проходит parse_start_payload → {} → source остаётся NULL
    assert row["source"] is None
