"""Скрипт замера прода (PR-0): 6 read-only запросов к БД метаданных.

Запуск: python scripts/prod_baseline.py
Ничего не пишет и не меняет — только SELECT через bot.db.database.get_db().
Вывод — готовый markdown-блок, который можно вставить в docs/BASELINE.md.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

# Позволяет запускать `python scripts/prod_baseline.py` из корня репозитория
# без ручной настройки PYTHONPATH — при запуске файла напрямую sys.path[0]
# указывает на scripts/, а не на корень, где лежит пакет bot.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import settings  # noqa: E402  (нужен sys.path.insert выше)
from bot.db.database import get_db  # noqa: E402


async def _fetchone(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> tuple:
    cur = await db.execute(sql, params)
    row = await cur.fetchone()
    return tuple(row) if row is not None else ()


async def _fetchall(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    cur = await db.execute(sql, params)
    return [tuple(r) for r in await cur.fetchall()]


async def main() -> None:
    lines: list[str] = [
        f"# Baseline замер прода — {datetime.now(timezone.utc):%Y-%m-%d} (UTC)",
        f"БД: `{settings.db_path}`",
        "",
    ]

    async with get_db() as db:
        # 1) Минуты использования (порог 38 мин — см. README про unit-экономику).
        users_with_usage, avg_minutes, max_minutes, users_over_38 = await _fetchone(
            db,
            """
            SELECT COUNT(*), ROUND(AVG(minutes_used), 2), ROUND(MAX(minutes_used), 2),
                   SUM(CASE WHEN minutes_used >= 38 THEN 1 ELSE 0 END)
            FROM users WHERE minutes_used > 0;
            """,
        ) or (0, None, None, None)
        lines += [
            "## 1. Минуты использования (порог 38 мин)",
            f"- Пользователей с ненулевым расходом: **{users_with_usage}**",
            f"- Среднее minutes_used: **{avg_minutes}**",
            f"- Максимум minutes_used: **{max_minutes}**",
            f"- Из них с расходом ≥ 38 мин: **{users_over_38}**",
            "",
        ]

        # 2) Пэйвол.
        (paywall_users,) = await _fetchone(
            db, "SELECT COUNT(DISTINCT user_id) FROM events WHERE type='paywall';"
        ) or (0,)
        lines += [
            "## 2. Пользователи, упёршиеся в пэйвол",
            f"- Уникальных пользователей: **{paywall_users}**",
            "",
        ]

        # 3) Распознавания по часам / в день.
        top_hours = await _fetchall(
            db,
            """
            SELECT strftime('%Y-%m-%d %H:00', created_at) AS hb, COUNT(*)
            FROM events WHERE type='recognize'
            GROUP BY hb ORDER BY COUNT(*) DESC LIMIT 10;
            """,
        )
        avg_per_day, days_with_data = await _fetchone(
            db,
            """
            SELECT ROUND(1.0 * COUNT(*) / NULLIF(COUNT(DISTINCT DATE(created_at)), 0), 2),
                   COUNT(DISTINCT DATE(created_at))
            FROM events WHERE type='recognize';
            """,
        ) or (None, 0)
        lines += ["## 3. Распознавания в час (топ-10) и в среднем за день"]
        if top_hours:
            lines.append("| Час | Распознаваний |")
            lines.append("|---|---|")
            lines += [f"| {hour} | {cnt} |" for hour, cnt in top_hours]
        else:
            lines.append("_данных нет_")
        lines += [f"- Среднее в день: **{avg_per_day}** (дней с данными: {days_with_data})", ""]

        # 4) Итоги vs маркетинговое «5000+ пользователей».
        total_users, total_recognitions, total_hours = await _fetchone(
            db,
            """
            SELECT (SELECT COUNT(*) FROM users),
                   (SELECT COUNT(*) FROM events WHERE type='recognize'),
                   (SELECT ROUND(SUM(duration_sec) / 3600.0, 1) FROM events WHERE type='recognize');
            """,
        ) or (0, 0, None)
        lines += [
            "## 4. Итоги vs маркетинговое «5000+ пользователей»",
            f"- Всего пользователей: **{total_users}**",
            f"- Всего распознаваний: **{total_recognitions}**",
            f"- Суммарно распознано часов: **{total_hours}**",
            "",
        ]

        # 5) Баг «документ не тарифицируется».
        without_duration, recognize_total = await _fetchone(
            db,
            """
            SELECT (SELECT COUNT(*) FROM events WHERE type='recognize' AND duration_sec IS NULL),
                   (SELECT COUNT(*) FROM events WHERE type='recognize');
            """,
        ) or (0, 0)
        lines += [
            "## 5. Распознавания без duration_sec (баг «документ не тарифицируется»)",
            f"- Без duration_sec: **{without_duration}** из **{recognize_total}**",
            "",
        ]

        # 6) Объём records.transcript — вход для решения о retention.
        records_count, total_chars, total_mb, oldest_at = await _fetchone(
            db,
            """
            SELECT COUNT(*), SUM(LENGTH(transcript)),
                   ROUND(SUM(LENGTH(transcript)) / 1048576.0, 2), MIN(created_at)
            FROM records;
            """,
        ) or (0, None, None, None)
        lines += [
            "## 6. Объём records.transcript (для решения о retention)",
            f"- Записей: **{records_count}**",
            f"- Суммарно символов: **{total_chars}**",
            f"- Примерный объём: **{total_mb} МБ**",
            f"- Самая старая запись: **{oldest_at}**",
            "",
        ]

    print("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())
