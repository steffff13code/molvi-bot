from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite

from bot.config import settings


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    _ensure_parent_dir(settings.db_path)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        db.row_factory = aiosqlite.Row
        yield db


async def init_db() -> None:
    _ensure_parent_dir(settings.db_path)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tg_file_id TEXT,
                duration_sec INTEGER,
                transcript TEXT,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS outputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
                UNIQUE(record_id, type)
            );

            CREATE INDEX IF NOT EXISTS idx_records_user ON records(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_outputs_record ON outputs(record_id);
            """
        )

        await db.commit()

