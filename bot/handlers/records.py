from __future__ import annotations

import asyncio

from aiogram import F, Router, types
from loguru import logger

from bot.config import settings
from bot.db.queries import (
    count_records,
    delete_record,
    get_output,
    get_record,
    list_records,
    upsert_output,
)
from bot.keyboards.inline import download_format_kb, record_actions_kb, records_pager_kb
from bot.keyboards.reply import main_menu_kb
from bot.prompts import system_prompts
from bot.services.export import build_export
from bot.services.gigachat import GigaChatClient
from bot.services.retry import with_retries
from bot.utils import as_txt_file, split_telegram_text


router = Router()

gigachat_client = GigaChatClient(
    auth_key=settings.gigachat_auth_key,
    scope=settings.gigachat_scope,
    model=settings.gigachat_model,
)


def _format_record_button(item) -> str:
    dur = ""
    if item.duration_sec:
        m = item.duration_sec // 60
        s = item.duration_sec % 60
        dur = f" ({m}:{s:02d})"
    title = item.title
    return f"📅 {item.created_at[:16]} — {title}{dur}"


@router.message(lambda m: m.text == "📂 Мои записи")
async def my_records(message: types.Message) -> None:
    await _send_records_page(message, offset=0)


@router.callback_query(F.data.startswith("reclist:"))
async def records_page(cb: types.CallbackQuery) -> None:
    try:
        offset = int(cb.data.split(":", 1)[1])
    except Exception:
        offset = 0
    await _send_records_page(cb.message, offset=offset, edit=True)  # type: ignore[arg-type]
    await cb.answer()


async def _send_records_page(message: types.Message, offset: int, edit: bool = False) -> None:
    user = message.chat
    if not user:
        return
    items = await list_records(user_id=user.id, limit=10, offset=offset)
    total = await count_records(user_id=user.id)

    if not items:
        text = "У вас пока нет записей. Отправьте голосовое или аудиофайл."
        if edit:
            await message.edit_text(text, reply_markup=None)
        else:
            await message.answer(text, reply_markup=main_menu_kb())
        return

    kb_rows = []
    for it in items:
        kb_rows.append([types.InlineKeyboardButton(text=_format_record_button(it), callback_data=f"recopen:{it.id}")])

    has_prev = offset > 0
    has_next = (offset + 10) < total
    pager = records_pager_kb(offset, has_prev=has_prev, has_next=has_next)
    if pager.inline_keyboard:
        kb_rows.extend(pager.inline_keyboard)

    kb = types.InlineKeyboardMarkup(inline_keyboard=kb_rows)
    text = "Ваши последние записи:"
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("recopen:"))
async def open_record(cb: types.CallbackQuery) -> None:
    user = cb.from_user
    if not user or not cb.message:
        return
    record_id = int(cb.data.split(":", 1)[1])
    rec = await get_record(record_id, user.id)
    if not rec:
        await cb.answer("Запись не найдена", show_alert=True)
        return
    await cb.message.edit_text("Что сделать с записью?", reply_markup=record_actions_kb(record_id))
    await cb.answer()


@router.callback_query(F.data.startswith("dl:"))
async def download_fulltext(cb: types.CallbackQuery) -> None:
    user = cb.from_user
    if not user or not cb.message:
        return

    _, record_id_str, fmt = cb.data.split(":", 2)
    record_id = int(record_id_str)

    rec = await get_record(record_id, user.id)
    if not rec:
        await cb.answer("Запись не найдена", show_alert=True)
        return

    transcript = (rec.get("transcript") or "").strip()
    if not transcript:
        await cb.answer("Пустая расшифровка", show_alert=True)
        return

    await cb.answer("Готовлю файл…")

    try:
        title = rec.get("title") or "Расшифровка"
        data, filename = await asyncio.to_thread(build_export, fmt, title, transcript)
        document = types.BufferedInputFile(data, filename=filename)
        await cb.message.answer_document(
            document,
            caption=f"📄 Полный текст ({fmt.upper()})",
        )
        await cb.message.answer(
            "Что ещё сделать с записью?",
            reply_markup=record_actions_kb(record_id),
        )
    except Exception as e:
        logger.exception("Export failed: {e}", e=e)
        await cb.message.answer(
            "⚠️ Не удалось сформировать файл. Попробуйте другой формат.",
            reply_markup=record_actions_kb(record_id),
        )


@router.callback_query(F.data.startswith("rec:"))
async def record_action(cb: types.CallbackQuery) -> None:
    user = cb.from_user
    if not user or not cb.message:
        return

    _, record_id_str, action = cb.data.split(":", 2)
    record_id = int(record_id_str)

    rec = await get_record(record_id, user.id)
    if not rec:
        await cb.answer("Запись не найдена", show_alert=True)
        return

    if action == "delete":
        ok = await delete_record(record_id, user.id)
        await cb.message.edit_text("🗑 Запись удалена." if ok else "Не удалось удалить запись.")
        await cb.answer()
        return

    if action == "fulltext":
        text = (rec.get("transcript") or "").strip()
        if not text:
            await cb.answer("Пустая расшифровка", show_alert=True)
            return
        await cb.message.edit_text(
            "📄 В каком формате скачать полный текст?",
            reply_markup=download_format_kb(record_id),
        )
        await cb.answer()
        return

    # summary/todo/roadmap/keywords — сначала кэш
    cached = await get_output(record_id, action)  # type: ignore[arg-type]
    if cached:
        await _send_long_text(cb.message, "Готово (из кэша):", cached)
        await cb.answer()
        return

    transcript = (rec.get("transcript") or "").strip()
    if not transcript:
        await cb.answer("Пустая расшифровка", show_alert=True)
        return

    await cb.message.edit_text("⏳ Обрабатываю через GigaChat…", reply_markup=None)

    try:
        if action == "summary":
            prompt = system_prompts.SUMMARY.format(transcript=transcript)
        elif action == "todo":
            prompt = system_prompts.TODO.format(transcript=transcript)
        elif action == "roadmap":
            prompt = system_prompts.ROADMAP.format(transcript=transcript)
        elif action == "keywords":
            prompt = system_prompts.KEYWORDS.format(transcript=transcript)
        else:
            await cb.message.edit_text("Неизвестное действие.")
            await cb.answer()
            return

        content = await with_retries(
            lambda: gigachat_client.complete(system="Ты — помощник для структурирования заметок.", user=prompt),
            attempts=3,
            base_delay=1.0,
        )
        await upsert_output(record_id, action, content)  # type: ignore[arg-type]

        await _send_long_text(cb.message, "Готово:", content, reply_markup=record_actions_kb(record_id))
    except Exception as e:
        logger.exception("GigaChat action failed: {e}", e=e)
        await cb.message.edit_text("⚠️ Не удалось обработать через GigaChat. Попробуйте ещё раз.", reply_markup=record_actions_kb(record_id))
    finally:
        await cb.answer()


async def _send_long_text(message: types.Message, prefix: str, text: str, reply_markup=None) -> None:
    full = f"{prefix}\n\n{text}".strip()
    parts = split_telegram_text(full)
    if len(parts) == 1 and len(parts[0]) <= 4096:
        await message.edit_text(parts[0], reply_markup=reply_markup)
        return
    if len(full) <= 15000:
        # отправим несколькими сообщениями, первое — редактируем, остальные — отдельно
        await message.edit_text(parts[0])
        for p in parts[1:]:
            await message.answer(p)
        if reply_markup:
            await message.answer("Выберите действие:", reply_markup=reply_markup)
        return

    # если очень длинно — как файл
    await message.edit_text(prefix)
    await message.answer_document(as_txt_file("molvi.txt", text))
    if reply_markup:
        await message.answer("Выберите действие:", reply_markup=reply_markup)

