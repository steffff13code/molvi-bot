from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Optional

from bot.db.database import get_db


OutputType = Literal["summary", "todo", "roadmap", "keywords", "fulltext"]


@dataclass(frozen=True)
class RecordListItem:
    id: int
    created_at: str
    title: str
    duration_sec: int | None


async def upsert_user(user_id: int, username: str | None, first_name: str | None) -> None:
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO users(user_id, username, first_name)
            VALUES(?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name;
            """,
            (user_id, username, first_name),
        )
        await db.commit()


async def create_record(
    *,
    user_id: int,
    tg_file_id: str | None,
    duration_sec: int | None,
    transcript: str,
) -> int:
    title = (transcript or "").strip().replace("\n", " ")
    if len(title) > 50:
        title = title[:50].rstrip() + "…"
    if not title:
        title = "Запись"

    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO records(user_id, tg_file_id, duration_sec, transcript, title)
            VALUES(?, ?, ?, ?, ?);
            """,
            (user_id, tg_file_id, duration_sec, transcript, title),
        )
        await db.commit()
        return int(cur.lastrowid)


async def get_record(record_id: int, user_id: int) -> Optional[dict]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT id, user_id, tg_file_id, duration_sec, transcript, title, created_at
            FROM records
            WHERE id=? AND user_id=?;
            """,
            (record_id, user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def delete_record(record_id: int, user_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM records WHERE id=? AND user_id=?;",
            (record_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def list_records(user_id: int, limit: int = 10, offset: int = 0) -> list[RecordListItem]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT id, created_at, title, duration_sec
            FROM records
            WHERE user_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?;
            """,
            (user_id, limit, offset),
        )
        rows = await cur.fetchall()
        return [RecordListItem(id=int(r["id"]), created_at=str(r["created_at"]), title=str(r["title"]), duration_sec=r["duration_sec"]) for r in rows]


async def count_records(user_id: int) -> int:
    async with get_db() as db:
        cur = await db.execute("SELECT COUNT(1) AS c FROM records WHERE user_id=?;", (user_id,))
        row = await cur.fetchone()
        return int(row["c"]) if row else 0


async def get_output(record_id: int, type_: OutputType) -> str | None:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT content FROM outputs WHERE record_id=? AND type=?;",
            (record_id, type_),
        )
        row = await cur.fetchone()
        return str(row["content"]) if row and row["content"] is not None else None


async def upsert_output(record_id: int, type_: OutputType, content: str) -> None:
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO outputs(record_id, type, content)
            VALUES(?, ?, ?)
            ON CONFLICT(record_id, type) DO UPDATE SET
                content=excluded.content,
                created_at=CURRENT_TIMESTAMP;
            """,
            (record_id, type_, content),
        )
        await db.commit()

