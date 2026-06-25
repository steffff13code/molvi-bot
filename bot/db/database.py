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
    """Создаёт схему МЕТАДАННЫХ (Вариант А — контент пользователей не хранится).

    В БД нет ни расшифровок, ни саммари, ни файлов — только обезличиваемые
    метаданные для лимитов и агрегированной статистики.
    """
    _ensure_parent_dir(settings.db_path)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                consent_at TIMESTAMP,
                minutes_used REAL NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Журнал событий для агрегированной статистики (без контента).
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,            -- recognize | template | paywall | error | export
                template TEXT,                 -- ключ шаблона (для разбивки)
                fmt TEXT,                      -- формат экспорта (txt/pdf/docx)
                duration_sec INTEGER,          -- длительность распознанной записи
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Белый список (безлимит). Только идентификатор, без контента.
            CREATE TABLE IF NOT EXISTS whitelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER UNIQUE,
                username TEXT UNIQUE,          -- нижний регистр, без '@'
                note TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- История расшифровок пользователя (для "Мои записи").
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                duration_sec INTEGER,
                transcript TEXT NOT NULL,
                template TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
            CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(type, created_at);
            CREATE INDEX IF NOT EXISTS idx_records_user ON records(user_id, created_at);
            """
        )

        # Мягкие миграции для старых БД (если колонок ещё нет).
        await _ensure_column(db, "users", "consent_at", "TIMESTAMP")
        await _ensure_column(db, "users", "minutes_used", "REAL NOT NULL DEFAULT 0")
        await _ensure_column(db, "users", "last_seen_at", "TIMESTAMP")

        await db.commit()


async def _ensure_column(db: aiosqlite.Connection, table: str, column: str, decl: str) -> None:
    cur = await db.execute(f"PRAGMA table_info({table});")
    cols = {row[1] for row in await cur.fetchall()}
    if column not in cols:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl};")
