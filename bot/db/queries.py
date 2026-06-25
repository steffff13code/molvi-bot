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


async def gift_minutes(user_id: int, minutes: float) -> bool:
    """Подарить пользователю N минут — вычитает из minutes_used и фиксирует в gifted_minutes."""
    async with get_db() as db:
        cur = await db.execute(
            """UPDATE users
               SET minutes_used   = COALESCE(minutes_used, 0)   - ?,
                   gifted_minutes = COALESCE(gifted_minutes, 0) + ?
               WHERE user_id=?;""",
            (minutes, minutes, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_user_info(user_id: int) -> dict | None:
    """Полная информация по пользователю для админа."""
    async with get_db() as db:
        cur = await db.execute(
            """SELECT user_id, username, first_name, consent_at,
                      minutes_used, gifted_minutes, created_at, last_seen_at
               FROM users WHERE user_id=?;""",
            (user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        # Whitelist check
        cur2 = await db.execute(
            "SELECT id, note, added_at FROM whitelist WHERE tg_id=? LIMIT 1;",
            (user_id,),
        )
        wl = await cur2.fetchone()
        d["whitelist"] = dict(wl) if wl else None
        return d


# ───────────────────────── Whitelist (безлимит) ─────────────────────────

def _norm_username(username: str | None) -> str | None:
    if not username:
        return None
    return username.lstrip("@").strip().lower() or None


async def is_whitelisted(user_id: int, username: str | None) -> bool:
    from bot.config import settings  # локальный импорт во избежание цикличности
    if settings.admin_id and user_id == settings.admin_id:
        return True
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


async def save_record(user_id: int, transcript: str, duration_sec: int | None, template: str | None = None) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO records(user_id, transcript, duration_sec, template) VALUES(?, ?, ?, ?);",
            (user_id, transcript, duration_sec, template),
        )
        await db.commit()
        return cur.lastrowid or 0


async def get_user_records(user_id: int, limit: int = 10) -> list[dict]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id, duration_sec, transcript, template, created_at FROM records "
            "WHERE user_id=? ORDER BY created_at DESC LIMIT ?;",
            (user_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_record(record_id: int, user_id: int) -> Optional[dict]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id, duration_sec, transcript, template, created_at FROM records "
            "WHERE id=? AND user_id=?;",
            (record_id, user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


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
    """Агрегаты для веб-админки (без контента)."""
    return await get_stats_full(days, exclude_admin=False)


async def get_stats_full(days: int = 30, exclude_admin: bool = True) -> dict:
    """Детальная статистика для Telegram-команды /stats.

    days=0 означает «за всё время».
    exclude_admin=True исключает ADMIN_ID из всех пользовательских счётчиков.
    """
    from bot.config import settings  # локальный импорт во избежание цикличности

    admin_id: int = settings.admin_id if exclude_admin and settings.admin_id else 0

    async with get_db() as db:
        async def scalar(sql: str, params: tuple = ()) -> float:
            cur = await db.execute(sql, params)
            row = await cur.fetchone()
            val = row[0] if row else 0
            return float(val) if val is not None else 0.0

        # Параметры фильтра по времени
        if days > 0:
            since = f"-{int(days)} days"
            tf_u = "AND created_at >= datetime('now', ?)"       # для таблицы users
            tf_e = "AND created_at >= datetime('now', ?)"       # для таблицы events
            p_u = (since,)
            p_e = (since,)
        else:
            tf_u = tf_e = ""
            p_u = p_e = ()

        # Фильтр исключения админа
        excl_u = f"AND user_id != {admin_id}" if admin_id else ""
        excl_e = f"AND user_id != {admin_id}" if admin_id else ""

        # ── Пользователи ──────────────────────────────────────────────
        total_users = int(await scalar(
            f"SELECT COUNT(*) FROM users WHERE 1=1 {excl_u};",
        ))
        new_users = int(await scalar(
            f"SELECT COUNT(*) FROM users WHERE 1=1 {tf_u} {excl_u};", p_u,
        ))
        # Пользователи, которые отправили хотя бы одно аудио за период
        audio_users = int(await scalar(
            f"SELECT COUNT(DISTINCT user_id) FROM events "
            f"WHERE type='recognize' {tf_e} {excl_e};", p_e,
        ))
        # Всего уникальных отправителей аудио за всё время (для воронки)
        audio_users_total = int(await scalar(
            f"SELECT COUNT(DISTINCT user_id) FROM events "
            f"WHERE type='recognize' {excl_e};",
        ))
        # Уникальные пользователи, упёршиеся в пэйвол за период
        paywall_users = int(await scalar(
            f"SELECT COUNT(DISTINCT user_id) FROM events "
            f"WHERE type='paywall' {tf_e} {excl_e};", p_e,
        ))
        # DAU / WAU / MAU (исключая админа)
        dau = int(await scalar(
            f"SELECT COUNT(DISTINCT user_id) FROM events "
            f"WHERE created_at >= datetime('now','-1 day') {excl_e};"
        ))
        wau = int(await scalar(
            f"SELECT COUNT(DISTINCT user_id) FROM events "
            f"WHERE created_at >= datetime('now','-7 days') {excl_e};"
        ))
        mau = int(await scalar(
            f"SELECT COUNT(DISTINCT user_id) FROM events "
            f"WHERE created_at >= datetime('now','-30 days') {excl_e};"
        ))

        # ── Расшифровки ────────────────────────────────────────────────
        files = int(await scalar(
            f"SELECT COUNT(*) FROM events WHERE type='recognize' {tf_e} {excl_e};", p_e,
        ))
        minutes = await scalar(
            f"SELECT COALESCE(SUM(duration_sec),0)/60.0 FROM events "
            f"WHERE type='recognize' {tf_e} {excl_e};", p_e,
        )
        avg_len = await scalar(
            f"SELECT COALESCE(AVG(duration_sec),0)/60.0 FROM events "
            f"WHERE type='recognize' {tf_e} {excl_e};", p_e,
        )
        max_len = await scalar(
            f"SELECT COALESCE(MAX(duration_sec),0)/60.0 FROM events "
            f"WHERE type='recognize' {tf_e} {excl_e};", p_e,
        )
        # Когда была последняя расшифровка (любого пользователя)
        cur = await db.execute(
            f"SELECT created_at FROM events WHERE type='recognize' {excl_e} "
            f"ORDER BY created_at DESC LIMIT 1;",
        )
        row = await cur.fetchone()
        last_recognize_at: str | None = str(row[0]) if row else None

        # ── Пэйвол / ошибки ───────────────────────────────────────────
        paywall_hits = int(await scalar(
            f"SELECT COUNT(*) FROM events WHERE type='paywall' {tf_e} {excl_e};", p_e,
        ))
        errors = int(await scalar(
            f"SELECT COUNT(*) FROM events WHERE type='error' {tf_e} {excl_e};", p_e,
        ))

        # ── Шаблоны (топ-8) ───────────────────────────────────────────
        cur = await db.execute(
            f"SELECT COALESCE(template,'plain') AS t, COUNT(*) AS c "
            f"FROM events WHERE type='template' {tf_e} {excl_e} "
            f"GROUP BY t ORDER BY c DESC LIMIT 8;", p_e,
        )
        templates = {str(r["t"]): int(r["c"]) for r in await cur.fetchall()}

        # ── Экспорт ───────────────────────────────────────────────────
        cur = await db.execute(
            f"SELECT COALESCE(fmt,'?') AS f, COUNT(*) AS c "
            f"FROM events WHERE type='export' {tf_e} {excl_e} "
            f"GROUP BY f ORDER BY c DESC;", p_e,
        )
        formats = {str(r["f"]): int(r["c"]) for r in await cur.fetchall()}
        exports_total = sum(formats.values())

        # ── Whitelist ─────────────────────────────────────────────────
        whitelist_count = int(await scalar("SELECT COUNT(*) FROM whitelist;"))

        return {
            "period_days": days,
            "users_total": total_users,
            "users_new": new_users,
            "users_audio": audio_users,          # отправили аудио за период
            "users_audio_total": audio_users_total,  # за всё время
            "users_paywall": paywall_users,       # упёрлись в лимит за период
            "dau": dau,
            "wau": wau,
            "mau": mau,
            "files": files,
            "minutes": round(minutes, 1),
            "avg_minutes": round(avg_len, 1),
            "max_minutes": round(max_len, 1),
            "last_recognize_at": last_recognize_at,
            "paywall_hits": paywall_hits,
            "errors": errors,
            "templates": templates,
            "formats": formats,
            "exports_total": exports_total,
            "whitelist_count": whitelist_count,
        }
