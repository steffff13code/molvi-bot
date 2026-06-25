from __future__ import annotations

import asyncio
import os
import uuid

from aiogram import Bot, F, Router, types
from loguru import logger

from bot.config import settings
from bot.db.queries import (
    add_minutes,
    get_minutes_used,
    has_consent,
    is_whitelisted,
    log_event,
    save_record,
    upsert_user,
)
from bot.keyboards.inline import choose_mode_kb, consent_kb, paywall_kb, result_kb, templates_kb
from bot.keyboards.reply import main_menu_kb
from bot.prompts.system_prompts import TEMPLATES, build_summary_prompt
from bot.services.audio import AUDIO_DIR, ensure_dirs, trim_audio
from bot.services.export import build_export
from bot.services.pricing import FREE_MINUTES, paywall_text
from bot.services.providers import STTQuotaError, get_llm, get_stt
from bot.services.retry import with_retries
from bot.services.session_store import session_store
from bot.utils import split_telegram_text

router = Router()

_stt = get_stt()
_llm = get_llm()


async def _recover_session(cb: types.CallbackQuery) -> str | None:
    """Когда сессия истекла — восстанавливает из последней записи БД.

    Возвращает новый token или None если записей нет.
    Отправляет сообщение пользователю с выбором действия.
    """
    from bot.db.queries import get_user_records
    user = cb.from_user
    if not user or not cb.message:
        return None
    records = await get_user_records(user.id, limit=1)
    if not records:
        await cb.answer("Сессия истекла. Пришлите запись заново.", show_alert=True)
        return None
    rec = records[0]
    new_token = session_store.put(user.id, rec["transcript"] or "", rec["duration_sec"])
    from bot.keyboards.inline import choose_mode_kb
    await cb.message.answer(
        "⏰ <b>Сессия истекла</b> — восстановил вашу последнюю расшифровку.\n"
        "Выберите, что с ней сделать:",
        parse_mode="HTML",
        reply_markup=choose_mode_kb(new_token),
    )
    await cb.answer()
    return new_token

# Поддерживаемые расширения для документов (на случай, если файл прислали «файлом»).
_SUPPORTED_DOC_EXTS = {
    ".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac", ".opus", ".wma", ".amr",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp",
}

CONSENT_REQUIRED_TEXT = (
    "Перед началом работы подтвердите согласие с документами — нажмите «✅ Подтвердить» "
    "в сообщении ниже. Это нужно один раз."
)

# Водяной знак, который вставляется в начало КАЖДОЙ расшифровки (файл и сообщение).
_WATERMARK = "Текст расшифрован МОЛВИ — https://molvi-ai.ru/\n\n"


def _watermarked(transcript: str) -> str:
    return _WATERMARK + transcript


def _ext_from_name(name: str | None) -> str:
    if not name:
        return ""
    _, ext = os.path.splitext(name)
    return ext.lower()


def _is_supported_document(doc: types.Document) -> bool:
    mime = (doc.mime_type or "").lower()
    if mime.startswith("audio/") or mime.startswith("video/"):
        return True
    return _ext_from_name(doc.file_name) in _SUPPORTED_DOC_EXTS


async def _ensure_consent(message: types.Message, user_id: int) -> bool:
    """True если согласие есть. Иначе показывает запрос согласия и возвращает False."""
    if await has_consent(user_id):
        return True
    await message.answer(
        "👋 Это МОЛВИ — расшифрую аудио в текст.\n\n" + CONSENT_REQUIRED_TEXT,
        reply_markup=consent_kb(),
    )
    return False


@router.message(lambda m: bool(m.voice or m.audio or m.document or m.video or m.video_note))
async def handle_audio(message: types.Message, bot: Bot) -> None:
    ensure_dirs()

    user = message.from_user
    if not user:
        return

    await upsert_user(user_id=user.id, username=user.username, first_name=user.first_name)

    if not await _ensure_consent(message, user.id):
        return

    tg_file_id: str | None = None
    duration_sec: int | None = None
    file_name: str | None = None
    file_size: int | None = None

    if message.voice:
        tg_file_id = message.voice.file_id
        duration_sec = message.voice.duration
        file_size = message.voice.file_size
        file_name = "voice.ogg"
    elif message.audio:
        tg_file_id = message.audio.file_id
        duration_sec = message.audio.duration
        file_size = message.audio.file_size
        file_name = message.audio.file_name
    elif message.video:
        tg_file_id = message.video.file_id
        duration_sec = message.video.duration
        file_size = message.video.file_size
        file_name = message.video.file_name or "video.mp4"
    elif message.video_note:
        tg_file_id = message.video_note.file_id
        duration_sec = message.video_note.duration
        file_size = message.video_note.file_size
        file_name = "video_note.mp4"
    elif message.document:
        if not _is_supported_document(message.document):
            await message.answer(
                "⚠️ Этот формат не поддерживается.\n\n"
                "Пришлите аудио, голосовое, видео или файл одного из форматов: "
                "MP3, WAV, OGG, M4A, FLAC, MP4, MOV и др.",
                reply_markup=main_menu_kb(),
            )
            return
        tg_file_id = message.document.file_id
        file_size = message.document.file_size
        file_name = message.document.file_name

    # Проверка размера файла (до скачивания с серверов Telegram).
    max_bytes = settings.max_audio_mb * 1024 * 1024
    if file_size is not None and file_size > max_bytes:
        await message.answer(
            f"⚠️ Файл слишком большой. Максимальный размер — {settings.max_audio_mb} МБ.",
            reply_markup=main_menu_kb(),
        )
        return

    if duration_sec is not None and duration_sec > settings.max_duration_sec:
        await message.answer(
            f"Запись слишком длинная. Лимит {settings.max_duration_sec // 60} мин.",
            reply_markup=main_menu_kb(),
        )
        return

    # Лимит/whitelist
    whitelisted = await is_whitelisted(user.id, user.username)
    remaining_sec: int | None = None  # None = безлимит
    trim_needed = False

    if not whitelisted:
        used = await get_minutes_used(user.id)
        remaining_min = FREE_MINUTES - used
        if remaining_min <= 0:
            await log_event(user_id=user.id, type_="paywall")
            await message.answer(
                paywall_text(),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=paywall_kb(),
            )
            return
        remaining_sec = int(remaining_min * 60)
        # Если длительность известна и превышает остаток — обрежем
        if duration_sec is not None and duration_sec > remaining_sec:
            trim_needed = True

    dur_text = f" ({duration_sec // 60} мин {duration_sec % 60} с)" if duration_sec else ""
    if trim_needed and remaining_sec:
        rem_min = remaining_sec // 60
        rem_sec = remaining_sec % 60
        status_msg = await message.answer(
            f"⏳ Принял запись{dur_text}.\n"
            f"⚠️ Вашего лимита хватит на <b>{rem_min} мин {rem_sec} с</b> — "
            f"расшифрую только эту часть. Идёт расшифровка…",
            parse_mode="HTML",
        )
    else:
        status_msg = await message.answer(
            f"⏳ Принял запись{dur_text}. Идёт расшифровка — подождите…"
        )

    uid = uuid.uuid4().hex
    ext = _ext_from_name(file_name) or ".mp3"
    source_path = str(AUDIO_DIR / f"{uid}_src{ext}")
    trimmed_path = str(AUDIO_DIR / f"{uid}_trim{ext}")

    try:
        tg_file = await bot.get_file(tg_file_id)  # type: ignore[arg-type]
        await bot.download_file(tg_file.file_path, destination=source_path)  # type: ignore[attr-defined]

        # Обрезка если не хватает лимита
        stt_path = source_path
        actual_duration_sec = duration_sec
        if trim_needed and remaining_sec:
            trimmed_dur = await trim_audio(source_path, trimmed_path, remaining_sec)
            if trimmed_dur < (duration_sec or 0):
                stt_path = trimmed_path
                actual_duration_sec = trimmed_dur

        transcript = await with_retries(
            lambda: _stt.transcribe(stt_path, actual_duration_sec), attempts=3, base_delay=2.0
        )
    except STTQuotaError:
        logger.error("STT quota exhausted (402)")
        await status_msg.edit_text(
            "⚠️ Сервис распознавания временно недоступен (исчерпан пакет). "
            "Мы уже пополняем баланс — попробуйте чуть позже."
        )
        return
    except Exception as e:
        logger.exception("Recognition failed: {e}", e=e)
        await log_event(user_id=user.id, type_="error")
        await status_msg.edit_text(
            "⚠️ Не удалось расшифровать запись. Попробуйте ещё раз через минуту."
        )
        return
    finally:
        # Вариант А: файлы удаляются сразу после распознавания.
        for p in (source_path, trimmed_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    # Учёт минут: списываем только реально расшифрованную часть.
    billed_sec = actual_duration_sec if trim_needed else duration_sec
    if billed_sec:
        await add_minutes(user.id, billed_sec / 60.0)
    await log_event(user_id=user.id, type_="recognize", duration_sec=billed_sec)

    # Сохраняем расшифровку в историю пользователя ("Мои записи").
    await save_record(user.id, transcript, duration_sec)

    # Транскрипт держим только в RAM на время сессии (для смены шаблона).
    token = session_store.put(user.id, transcript, duration_sec)

    # Показываем остаток лимита для обычных пользователей.
    balance_line = ""
    if not whitelisted:
        used_now = await get_minutes_used(user.id)
        remaining = max(0.0, FREE_MINUTES - used_now)
        balance_line = f"\n\n📊 Остаток бесплатных минут: <b>{remaining:.0f} из {FREE_MINUTES}</b>"

    await status_msg.edit_text(
        f"✅ Готово! Что сделать с записью?{balance_line}",
        parse_mode="HTML",
        reply_markup=choose_mode_kb(token),
    )


# ───────────────────────── Колбэки выбора режима/шаблона ─────────────────────────

@router.callback_query(F.data.startswith("m:"))
async def on_mode(cb: types.CallbackQuery) -> None:
    if not cb.from_user or not cb.message:
        return
    _, token, action = cb.data.split(":", 2)
    if action == "tpl":
        await cb.message.edit_text("📋 Выберите шаблон:", reply_markup=templates_kb(token))
        await cb.answer()
        return
    if action == "back":
        await cb.message.edit_text("Что сделать с записью?", reply_markup=choose_mode_kb(token))
        await cb.answer()
        return
    # plain / summary / roadmap / keypoints / tasks → все идут в _process
    await _process(cb, token, action)


@router.callback_query(F.data.startswith("t:"))
async def on_template(cb: types.CallbackQuery) -> None:
    _, token, key = cb.data.split(":", 2)
    await _process(cb, token, key)


@router.callback_query(F.data.startswith("chg:"))
async def on_change_template(cb: types.CallbackQuery) -> None:
    if not cb.message:
        return
    token = cb.data.split(":", 1)[1]
    if not session_store.get(token, cb.from_user.id if cb.from_user else 0):
        await _recover_session(cb)
        return
    await cb.message.answer("📋 Выберите другой шаблон:", reply_markup=choose_mode_kb(token))
    await cb.answer()


@router.callback_query(F.data.startswith("dl:"))
async def on_download(cb: types.CallbackQuery) -> None:
    user = cb.from_user
    if not user or not cb.message:
        return
    _, token, fmt = cb.data.split(":", 2)
    entry = session_store.get(token, user.id)
    if not entry:
        await _recover_session(cb)
        return
    await cb.answer("Готовлю файл…")
    try:
        body = _watermarked(entry.transcript)
        data, filename = await asyncio.to_thread(build_export, fmt, "Расшифровка МОЛВИ", body)
        await cb.message.answer_document(
            types.BufferedInputFile(data, filename=filename),
            caption=f"📄 Расшифровка ({fmt.upper()})",
        )
        await log_event(user_id=user.id, type_="export", fmt=fmt)
    except Exception as e:
        logger.exception("Export failed: {e}", e=e)
        await cb.message.answer("⚠️ Не удалось сформировать файл. Попробуйте другой формат.")


@router.callback_query(F.data.startswith("msg:"))
async def on_get_as_message(cb: types.CallbackQuery) -> None:
    """Полная расшифровка сообщением — только по запросу пользователя."""
    user = cb.from_user
    if not user or not cb.message:
        return
    token = cb.data.split(":", 1)[1]
    entry = session_store.get(token, user.id)
    if not entry:
        await _recover_session(cb)
        return
    await cb.answer()
    full = _watermarked(entry.transcript)
    for part in split_telegram_text(full):
        await cb.message.answer(part)


async def _process(cb: types.CallbackQuery, token: str, key: str) -> None:
    user = cb.from_user
    if not user or not cb.message:
        return
    entry = session_store.get(token, user.id)
    if not entry:
        await _recover_session(cb)
        return

    await cb.message.edit_text("⏳ Обрабатываю через GigaChat…", reply_markup=None)
    await cb.answer()

    transcript = entry.transcript
    try:
        system, prefix = build_summary_prompt(key)
        summary = await with_retries(
            lambda: _llm.summarize(text=prefix + transcript, system=system),
            attempts=3,
            base_delay=1.0,
        )
        await log_event(user_id=user.id, type_="template", template=key)
    except Exception as e:
        logger.exception("Summary failed: {e}", e=e)
        await log_event(user_id=user.id, type_="error")
        await cb.message.edit_text(
            "⚠️ Не удалось обработать через GigaChat. Попробуйте ещё раз.",
            reply_markup=result_kb(token),
        )
        return

    label = TEMPLATES.get(key, TEMPLATES["plain"]).label
    # 1) Структурированное саммари
    head = f"<b>{label}</b>\n\n{summary}".strip()
    parts = split_telegram_text(head)
    await cb.message.edit_text(parts[0], parse_mode="HTML")
    for p in parts[1:]:
        await cb.message.answer(p, parse_mode="HTML")

    # 2) Полную расшифровку НЕ вываливаем в чат — даём кнопки: файлом или сообщением.
    await cb.message.answer(
        "📄 <b>Полная расшифровка готова.</b>\n"
        "Скачайте файлом (TXT / PDF / DOCX) или получите сообщением 👇",
        parse_mode="HTML",
        reply_markup=result_kb(token),
    )
