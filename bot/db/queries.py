from __future__ import annotations

from typing import Optional

from bot.db.database import get_db


# ───────────────────────── Пользователи / согласие ─────────────────────────

async def upsert_user(user_id: int, username: str | None, first_name: str | None) -> None:
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO users(user_id, username, first_name)
            VALUES(?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_seen_at=CURRENT_TIMESTAMP;
            """,
            (user_id, username, first_name),
        )
        await db.commit()


async def has_consent(user_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute("SELECT consent_at FROM users WHERE user_id=?;", (user_id,))
        row = await cur.fetchone()
        return bool(row and row["consent_at"])


async def set_consent(user_id: int) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET consent_at=CURRENT_TIMESTAMP WHERE user_id=?;",
            (user_id,),
        )
        await db.commit()


# ───────────────────────── Лимиты / минуты ─────────────────────────

async def get_minutes_used(user_id: int) -> float:
    async with get_db() as db:
        cur = await db.execute("SELECT minutes_used FROM users WHERE user_id=?;", (user_id,))
        row = await cur.fetchone()
        return float(row["minutes_used"]) if row and row["minutes_used"] is not None else 0.0


async def add_minutes(user_id: int, minutes: float) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET minutes_used = COALESCE(minutes_used,0) + ? WHERE user_id=?;",
            (minutes, user_id),
        )
        await db.commit()


# ───────────────────────── Whitelist (безлимит) ─────────────────────────

def _norm_username(username: str | None) -> str | None:
    if not username:
        return None
    return username.lstrip("@").strip().lower() or None


async def is_whitelisted(user_id: int, username: str | None) -> bool:
    uname = _norm_username(username)
    async with get_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM whitelist WHERE tg_id=? OR (username IS NOT NULL AND username=?) LIMIT 1;",
            (user_id, uname),
        )
        return (await cur.fetchone()) is not None


async def whitelist_add(*, tg_id: int | None = None, username: str | None = None, note: str | None = None) -> bool:
    uname = _norm_username(username)
    if tg_id is None and uname is None:
        return False
    async with get_db() as db:
        try:
            await db.execute(
                "INSERT OR IGNORE INTO whitelist(tg_id, username, note) VALUES(?, ?, ?);",
                (tg_id, uname, note),
            )
            await db.commit()
            return True
        except Exception:
            return False


async def whitelist_remove(entry_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute("DELETE FROM whitelist WHERE id=?;", (entry_id,))
        await db.commit()
        return cur.rowcount > 0


async def whitelist_list() -> list[dict]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id, tg_id, username, note, added_at FROM whitelist ORDER BY added_at DESC;"
        )
        return [dict(r) for r in await cur.fetchall()]


# ───────────────────────── События / статистика ─────────────────────────

async def log_event(
    *,
    user_id: int,
    type_: str,
    template: str | None = None,
    fmt: str | None = None,
    duration_sec: int | None = None,
) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO events(user_id, type, template, fmt, duration_sec) VALUES(?, ?, ?, ?, ?);",
            (user_id, type_, template, fmt, duration_sec),
        )
        await db.commit()


async def get_stats(days: int = 30) -> dict:
    """Агрегаты для админки и /stats (без какого-либо контента)."""
    async with get_db() as db:
        async def scalar(sql: str, params: tuple = ()) -> float:
            cur = await db.execute(sql, params)
            row = await cur.fetchone()
            val = row[0] if row else 0
            return float(val) if val is not None else 0.0

        period = f"-{int(days)} days"

        total_users = int(await scalar("SELECT COUNT(*) FROM users;"))
        new_users = int(await scalar(
            "SELECT COUNT(*) FROM users WHERE created_at >= datetime('now', ?);", (period,)
        ))
        dau = int(await scalar(
            "SELECT COUNT(DISTINCT user_id) FROM events WHERE created_at >= datetime('now','-1 day');"
        ))
        wau = int(await scalar(
            "SELECT COUNT(DISTINCT user_id) FROM events WHERE created_at >= datetime('now','-7 days');"
        ))
        mau = int(await scalar(
            "SELECT COUNT(DISTINCT user_id) FROM events WHERE created_at >= datetime('now','-30 days');"
        ))
        files = int(await scalar(
            "SELECT COUNT(*) FROM events WHERE type='recognize' AND created_at >= datetime('now', ?);",
            (period,),
        ))
        minutes = await scalar(
            "SELECT COALESCE(SUM(duration_sec),0)/60.0 FROM events WHERE type='recognize' AND created_at >= datetime('now', ?);",
            (period,),
        )
        avg_len = await scalar(
            "SELECT COALESCE(AVG(duration_sec),0)/60.0 FROM events WHERE type='recognize' AND created_at >= datetime('now', ?);",
            (period,),
        )
        paywall_hits = int(await scalar(
            "SELECT COUNT(*) FROM events WHERE type='paywall' AND created_at >= datetime('now', ?);",
            (period,),
        ))
        errors = int(await scalar(
            "SELECT COUNT(*) FROM events WHERE type='error' AND created_at >= datetime('now', ?);",
            (period,),
        ))

        # Разбивка по шаблонам
        cur = await db.execute(
            "SELECT COALESCE(template,'(без шаблона)') AS t, COUNT(*) AS c "
            "FROM events WHERE type='template' AND created_at >= datetime('now', ?) "
            "GROUP BY t ORDER BY c DESC;",
            (period,),
        )
        templates = {str(r["t"]): int(r["c"]) for r in await cur.fetchall()}

        # Популярные форматы экспорта
        cur = await db.execute(
            "SELECT COALESCE(fmt,'?') AS f, COUNT(*) AS c "
            "FROM events WHERE type='export' AND created_at >= datetime('now', ?) "
            "GROUP BY f ORDER BY c DESC;",
            (period,),
        )
        formats = {str(r["f"]): int(r["c"]) for r in await cur.fetchall()}

        whitelist_count = int(await scalar("SELECT COUNT(*) FROM whitelist;"))

        return {
            "period_days": days,
            "users_total": total_users,
            "users_new": new_users,
            "dau": dau,
            "wau": wau,
            "mau": mau,
            "files": files,
            "minutes": round(minutes, 1),
            "avg_minutes": round(avg_len, 1),
            "paywall_hits": paywall_hits,
            "errors": errors,
            "templates": templates,
            "formats": formats,
            "whitelist_count": whitelist_count,
            "revenue": 0,            # оплата не подключена (информационный пэйвол)
            "conversion": None,      # н.д.
        }
