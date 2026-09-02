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
    async with aiosqlite.connect(settings.db_path, timeout=30) as db:
        await db.execute("PRAGMA journal_mode = WAL;")     # параллельное чтение при записи
        await db.execute("PRAGMA busy_timeout = 5000;")    # ждать блокировку, а не падать
        await db.execute("PRAGMA foreign_keys = ON;")
        # synchronous=NORMAL безопасен для метаданных; когда через эту БД пойдут
        # реальные платежи — переключить на FULL (отдельный будущий шаг).
        await db.execute("PRAGMA synchronous = NORMAL;")
        db.row_factory = aiosqlite.Row
        yield db


async def init_db() -> None:
    """Создаёт схему БД: метаданные (users/events/whitelist) + records.

    Аудиофайл удаляется сразу после обработки — сырых файлов в БД нет и не
    было. Текст расшифровки в records хранится records_retention_days дней
    (см. bot/config.py), после чего удаляется автоматически (cleanup.py) или
    раньше — командой /forget. См. PR-7.
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
                type TEXT NOT NULL,            -- recognize | template | paywall | error | export | llm_call | ...
                template TEXT,                 -- ключ шаблона (для разбивки)
                fmt TEXT,                      -- формат экспорта (txt/pdf/docx)
                duration_sec INTEGER,          -- длительность распознанной записи
                job_id TEXT,                   -- токен сессии — связывает recognize/template/llm_call одной записи
                err_code TEXT,                 -- причина ошибки (type='error')
                meta TEXT,                     -- произвольный контекст, без контента пользователя
                latency_ms INTEGER,            -- время внешнего вызова (type='llm_call')
                model TEXT,                    -- модель LLM (type='llm_call')
                pass_name TEXT,                -- имя прохода в конвейере рассуждения (PR-18+)
                tokens_in INTEGER,             -- токены запроса (type='llm_call')
                tokens_out INTEGER,            -- токены ответа (type='llm_call')
                tokens_cached INTEGER,         -- токены из кэша промпта (type='llm_call')
                pipeline_version TEXT,         -- версия промпта/конвейера
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
        await _ensure_column(db, "users", "gifted_minutes", "REAL NOT NULL DEFAULT 0")

        # Наблюдаемость (PR-5): job_id связывает recognize/template/llm_call одной записи
        # (нужно для доли смены шаблона — главной метрики качества саммари), err_code
        # разбивает ошибки по причине, остальное — метрики расхода токенов LLM.
        await _ensure_column(db, "events", "job_id", "TEXT")
        await _ensure_column(db, "events", "err_code", "TEXT")
        await _ensure_column(db, "events", "meta", "TEXT")
        await _ensure_column(db, "events", "latency_ms", "INTEGER")
        await _ensure_column(db, "events", "model", "TEXT")
        await _ensure_column(db, "events", "pass_name", "TEXT")
        await _ensure_column(db, "events", "tokens_in", "INTEGER")
        await _ensure_column(db, "events", "tokens_out", "INTEGER")
        await _ensure_column(db, "events", "tokens_cached", "INTEGER")
        await _ensure_column(db, "events", "pipeline_version", "TEXT")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, created_at);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_err ON events(type, err_code, created_at);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_model ON events(model, created_at);")

        await db.commit()


async def _ensure_column(db: aiosqlite.Connection, table: str, column: str, decl: str) -> None:
    cur = await db.execute(f"PRAGMA table_info({table});")
    cols = {row[1] for row in await cur.fetchall()}
    if column not in cols:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl};")
