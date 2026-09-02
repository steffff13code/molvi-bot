from __future__ import annotations

import html as _html
from datetime import datetime

from aiogram import F, Router, types

from bot.db.queries import delete_record, get_minutes_used, get_record, get_user_records, is_whitelisted, log_event
from bot.keyboards.inline import choose_mode_kb, paywall_kb
from bot.keyboards.reply import BTN_MY_RECORDS, main_menu_kb
from bot.services.nav_cleanup import nav_cleanup
from bot.services.pricing import FREE_MINUTES, paywall_text
from bot.services.session_store import session_store

router = Router()

_EMPTY_RECORDS_TEXT = (
    "📁 <b>Мои записи</b>\n\n"
    "У вас пока нет сохранённых расшифровок.\n\n"
    "Отправьте аудио, голосовое или видео — и я расшифрую его!"
)


def _fmt_duration(sec: int | None) -> str:
    if not sec:
        return ""
    m, s = divmod(sec, 60)
    return f"{m}:{s:02d}"


def _fmt_date(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_str.replace(" ", "T"))
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return dt_str[:10]


def _render_records_list(records: list[dict]) -> tuple[str, types.InlineKeyboardMarkup]:
    lines = ["📁 <b>Мои записи</b> (последние 10)\n"]
    buttons: list[list[types.InlineKeyboardButton]] = []

    for i, rec in enumerate(records, 1):
        dur = _fmt_duration(rec["duration_sec"])
        date = _fmt_date(rec["created_at"])
        transcript = rec["transcript"] or ""
        preview = _html.escape(transcript[:60].replace("\n", " "))
        if len(transcript) > 60:
            preview += "…"
        dur_str = f" · {dur}" if dur else ""
        lines.append(f"{i}. {date}{dur_str}\n    <i>{preview}</i>")
        buttons.append([
            types.InlineKeyboardButton(
                text=f"📄 Запись {i} · {date}{dur_str}",
                callback_data=f"rec:{rec['id']}",
            ),
            types.InlineKeyboardButton(text="🗑", callback_data=f"recdel:{rec['id']}"),
        ])

    lines.append("\n👆 Нажмите на запись, чтобы выбрать что с ней сделать.")
    return "\n".join(lines), types.InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(F.text == BTN_MY_RECORDS)
async def my_records(message: types.Message) -> None:
    user = message.from_user
    if not user:
        return

    records = await get_user_records(user.id, limit=10)
    if not records:
        sent = await message.answer(
            _EMPTY_RECORDS_TEXT, reply_markup=main_menu_kb(), parse_mode="HTML",
        )
        nav_cleanup.track(user.id, sent.message_id)
        return

    text, kb = _render_records_list(records)
    sent = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    # Список записей — транзитный, исчезает при отправке нового аудио
    nav_cleanup.track(user.id, sent.message_id)


@router.callback_query(F.data.startswith("recdel:"))
async def delete_record_cb(cb: types.CallbackQuery) -> None:
    user = cb.from_user
    if not user or not cb.message:
        return
    try:
        record_id = int(cb.data.split(":", 1)[1])
    except (ValueError, IndexError, AttributeError):
        await cb.answer("Неверный запрос.", show_alert=True)
        return

    ok = await delete_record(record_id, user.id)
    await cb.answer("Запись удалена." if ok else "Запись не найдена.", show_alert=not ok)
    if not ok:
        return

    records = await get_user_records(user.id, limit=10)
    if not records:
        await cb.message.edit_text(_EMPTY_RECORDS_TEXT, parse_mode="HTML")  # type: ignore[union-attr]
        return
    text, kb = _render_records_list(records)
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")  # type: ignore[union-attr]


@router.callback_query(F.data.startswith("rec:"))
async def view_record(cb: types.CallbackQuery) -> None:
    user = cb.from_user
    if not user or not cb.message:
        return

    try:
        record_id = int(cb.data.split(":", 1)[1])
    except ValueError:
        await cb.answer("Неверный запрос.", show_alert=True)
        return

    rec = await get_record(record_id, user.id)
    if not rec:
        await cb.answer("Запись не найдена.", show_alert=True)
        return

    await cb.answer()

    # Старая запись из «Моих записей» и так уже оплачена при первом распознавании,
    # но без этой проверки её можно было гонять через LLM бесконечно и бесплатно
    # даже после исчерпания лимита — ровно тот же обход, что и с шаблонами.
    if not await is_whitelisted(user.id, user.username):
        used = await get_minutes_used(user.id)
        if FREE_MINUTES - used <= 0:
            await log_event(user_id=user.id, type_="paywall")
            await cb.message.answer(
                paywall_text(), parse_mode="HTML", disable_web_page_preview=True,
                reply_markup=paywall_kb(),
            )
            return

    dur = _fmt_duration(rec["duration_sec"])
    date = _fmt_date(rec["created_at"])
    dur_str = f" · {dur}" if dur else ""

    # Кладём расшифровку в сессию и РЕДАКТИРУЕМ текущее сообщение (без нового)
    token = session_store.put(user.id, rec["transcript"] or "", rec["duration_sec"])
    await cb.message.edit_text(
        f"📄 <b>Запись от {date}{dur_str}</b>\n\nЧто сделать с этой расшифровкой?",
        parse_mode="HTML",
        reply_markup=choose_mode_kb(token),
    )
