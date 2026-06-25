from __future__ import annotations

from datetime import datetime

from aiogram import F, Router, types

from bot.db.queries import get_record, get_user_records
from bot.keyboards.inline import choose_mode_kb
from bot.keyboards.reply import BTN_MY_RECORDS, main_menu_kb
from bot.services.nav_cleanup import nav_cleanup
from bot.services.session_store import session_store

router = Router()


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


@router.message(F.text == BTN_MY_RECORDS)
async def my_records(message: types.Message) -> None:
    user = message.from_user
    if not user:
        return

    records = await get_user_records(user.id, limit=10)
    if not records:
        sent = await message.answer(
            "📁 <b>Мои записи</b>\n\n"
            "У вас пока нет сохранённых расшифровок.\n\n"
            "Отправьте аудио, голосовое или видео — и я расшифрую его!",
            reply_markup=main_menu_kb(),
            parse_mode="HTML",
        )
        nav_cleanup.track(user.id, sent.message_id)
        return

    lines = ["📁 <b>Мои записи</b> (последние 10)\n"]
    buttons: list[list[types.InlineKeyboardButton]] = []

    for i, rec in enumerate(records, 1):
        dur = _fmt_duration(rec["duration_sec"])
        date = _fmt_date(rec["created_at"])
        preview = (rec["transcript"] or "")[:60].replace("\n", " ")
        if len(rec["transcript"] or "") > 60:
            preview += "…"
        dur_str = f" · {dur}" if dur else ""
        lines.append(f"{i}. {date}{dur_str}\n    <i>{preview}</i>")
        buttons.append([
            types.InlineKeyboardButton(
                text=f"📄 Запись {i} · {date}{dur_str}",
                callback_data=f"rec:{rec['id']}",
            )
        ])

    lines.append("\n👆 Нажмите на запись, чтобы выбрать что с ней сделать.")

    kb = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    sent = await message.answer(
        "\n".join(lines),
        reply_markup=kb,
        parse_mode="HTML",
    )
    # Список записей — транзитный, исчезает при отправке нового аудио
    nav_cleanup.track(user.id, sent.message_id)


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
