from __future__ import annotations

import asyncio
import html as _html
import os
import uuid

from aiogram import Bot, F, Router, types
from loguru import logger

from bot.config import settings
from bot.db.queries import (
    add_minutes,
    create_job,
    finish_job,
    get_minutes_used,
    has_consent,
    is_whitelisted,
    log_event,
    save_record,
    upsert_user,
)
from bot.keyboards.inline import (
    ai_result_kb,
    choose_mode_kb,
    consent_kb,
    paywall_kb,
    plain_result_kb,
    templates_kb,
)
from bot.keyboards.reply import main_menu_kb
from bot.prompts.system_prompts import TEMPLATES, build_summary_prompt
from bot.services.audio import AUDIO_DIR, ensure_dirs, probe_duration, trim_audio
from bot.services.export import build_export
from bot.services.nav_cleanup import nav_cleanup
from bot.services.notify import notifier
from bot.services.pricing import FREE_MINUTES, paywall_text, template_limit_text
from bot.services.providers import STTQuotaError, get_llm, get_stt
from bot.services.retry import with_retries
from bot.services.session_store import session_store
from bot.utils import md_to_html, split_html_safe, split_telegram_text

router = Router()

_stt = get_stt()
_llm = get_llm()

# Самари отправляем файлом — оно длинное
_FILE_KEYS = {"summary"}

# Водяной знак в начале расшифровки
_WATERMARK = "Текст расшифрован МОЛВИ — https://molvi-ai.ru/\n\n"

# Максимальная длина текста в сообщении (с запасом на теги)
_MSG_LIMIT = 3800

# Неопознанная по длительности запись (ffprobe не смог определить) списывает
# этот минимум, а не ноль — иначе распознавание остаётся бесплатным.
MIN_BILLABLE_SEC = 30


def _watermarked(transcript: str) -> str:
    return _WATERMARK + transcript


async def _recover_session(cb: types.CallbackQuery) -> str | None:
    """Когда сессия истекла — восстанавливает из последней записи БД."""
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
    await cb.message.answer(
        "⏰ <b>Сессия истекла</b> — восстановил вашу последнюю расшифровку.\n"
        "Выберите, что с ней сделать:",
        parse_mode="HTML",
        reply_markup=choose_mode_kb(new_token),
    )
    await cb.answer()
    return new_token


# Поддерживаемые расширения документов
_SUPPORTED_DOC_EXTS = {
    ".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac", ".opus", ".wma", ".amr",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp",
}

CONSENT_REQUIRED_TEXT = (
    "Перед началом работы подтвердите согласие с документами — нажмите «✅ Подтвердить» "
    "в сообщении ниже. Это нужно один раз."
)


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

    # Удаляем транзитные навигационные сообщения (тарифы, помощь, записи)
    await nav_cleanup.clean(user.id, message.chat.id, bot)

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

    max_bytes = settings.effective_max_mb * 1024 * 1024
    if file_size is not None and file_size > max_bytes:
        # err_code появится в events, когда PR-5 добавит эту колонку
        await log_event(user_id=user.id, type_="error")
        await message.answer(
            f"⚠️ Файл {file_size / 1048576:.0f} МБ — это больше, чем Telegram отдаёт ботам.\n\n"
            f"Предел — <b>{settings.effective_max_mb} МБ</b>, и он задан самим Telegram, "
            f"а не нами. Что можно сделать:\n"
            f"— записать голосовым прямо в чат (час речи ≈ 9 МБ);\n"
            f"— пересжать в MP3 64 kbps моно (час ≈ 28 МБ, полтора часа не влезет);\n"
            f"— прислать запись частями.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(),
        )
        return

    if duration_sec is not None and duration_sec > settings.effective_max_duration_sec:
        await log_event(user_id=user.id, type_="error")
        await message.answer(
            f"Запись слишком длинная. Лимит {settings.effective_max_duration_sec // 60} мин.",
            reply_markup=main_menu_kb(),
        )
        return

    whitelisted = await is_whitelisted(user.id, user.username)
    remaining_sec: int | None = None
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
        if duration_sec is not None and duration_sec > remaining_sec:
            trim_needed = True

    # Для документа Telegram не отдаёт duration — длительность узнаём только после
    # скачивания (через ffprobe), поэтому лимит и trim_needed для него повторно
    # проверяются ниже, сразу после скачивания.
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
    elif duration_sec is not None:
        status_msg = await message.answer(
            f"⏳ Принял запись{dur_text}. Идёт расшифровка — подождите…"
        )
    else:
        status_msg = await message.answer("⏳ Принял запись. Скачиваю…")

    uid = uuid.uuid4().hex
    ext = _ext_from_name(file_name) or ".mp3"
    source_path = str(AUDIO_DIR / f"{uid}_src{ext}")
    trimmed_path = str(AUDIO_DIR / f"{uid}_trim{ext}")

    try:
        tg_file = await bot.get_file(tg_file_id)  # type: ignore[arg-type]
        await bot.download_file(tg_file.file_path, destination=source_path)  # type: ignore[attr-defined]
    except Exception as e:
        logger.error("File download failed: {e}", e=e)
        err_text = str(e).lower()
        too_big = "file is too big" in err_text or "too big" in err_text or "file_too_big" in err_text
        await log_event(
            user_id=user.id, type_="error",
            err_code="download_too_big" if too_big else "download_other",
        )
        if too_big:
            await status_msg.edit_text(
                f"⚠️ Файл слишком большой для загрузки через Telegram.\n\n"
                f"Максимальный размер — <b>{settings.effective_max_mb} МБ</b>. "
                f"Сожмите файл или пришлите часть записи.",
                parse_mode="HTML",
            )
        else:
            await status_msg.edit_text(
                "⚠️ Не удалось загрузить файл от Telegram. Попробуйте ещё раз через минуту."
            )
        return

    if duration_sec is None:
        # Документ — Telegram не прислал длительность, определяем её по самому файлу.
        duration_sec = await probe_duration(source_path)
        if duration_sec is not None and duration_sec > settings.effective_max_duration_sec:
            await log_event(user_id=user.id, type_="error")
            await status_msg.edit_text(
                f"Запись слишком длинная. Лимит {settings.effective_max_duration_sec // 60} мин."
            )
            if os.path.exists(source_path):
                os.remove(source_path)
            return
        if remaining_sec is not None and duration_sec is not None and duration_sec > remaining_sec:
            trim_needed = True
            rem_min, rem_sec = divmod(remaining_sec, 60)
            await status_msg.edit_text(
                f"⏳ Принял запись ({duration_sec // 60} мин {duration_sec % 60} с).\n"
                f"⚠️ Вашего лимита хватит на <b>{rem_min} мин {rem_sec} с</b> — "
                f"расшифрую только эту часть. Идёт расшифровка…",
                parse_mode="HTML",
            )
        else:
            await status_msg.edit_text("Идёт расшифровка — подождите…")

    # jobs (PR-20): от начала STT до показа результата пользователю уже могут быть
    # списаны минуты — если процесс убьют посреди этого окна (рестарт Railway),
    # запись останется 'processing' и её найдёт jobs_recovery.py при следующем
    # старте, вместо того чтобы пользователь смотрел на вечное «⏳» и, не зная,
    # что расшифровка уже готова и оплачена, прислал файл повторно.
    job_id = await create_job(user.id, kind="recognize")

    try:
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
        # Сервис лежит для ВСЕХ пользователей — владелец должен узнавать об этом
        # из events и от бота, а не от пользователей в поддержке.
        await log_event(user_id=user.id, type_="error", err_code="stt_quota")
        notifier.notify("provider_quota", "🔥 STT-провайдер вернул 402 — пакет распознавания исчерпан.")
        await finish_job(job_id, "failed")
        await status_msg.edit_text(
            "⚠️ Сервис распознавания временно недоступен (исчерпан пакет). "
            "Мы уже пополняем баланс — попробуйте чуть позже."
        )
        return
    except Exception as e:
        logger.exception("Recognition failed: {e}", e=e)
        await log_event(user_id=user.id, type_="error", err_code="stt_fail")
        await finish_job(job_id, "failed")
        await status_msg.edit_text(
            "⚠️ Не удалось расшифровать запись. Попробуйте ещё раз через минуту."
        )
        return
    finally:
        for p in (source_path, trimmed_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    billed_sec = actual_duration_sec if trim_needed else duration_sec
    # Неопознанная по длительности запись (документ, ffprobe не справился) списывает
    # минимум, а не ноль — иначе распознавание для неё остаётся бесплатным.
    billed_sec = billed_sec or MIN_BILLABLE_SEC

    try:
        # save_record — ПЕРВЫМ: если упадёт именно он, минуты ещё не списаны,
        # и пользователь не остаётся без текста при уже оплаченном вызове STT.
        await save_record(user.id, transcript, duration_sec)
        await add_minutes(user.id, billed_sec / 60.0)

        # token — ДО log_event('recognize'), чтобы передать его как job_id: без этой
        # связки template/llm_call этой же записи нечем скоррелировать с recognize,
        # и долю смены шаблона (главная метрика качества саммари) не посчитать.
        token = session_store.put(user.id, transcript, duration_sec)
        await log_event(user_id=user.id, type_="recognize", duration_sec=billed_sec, job_id=token)

        balance_line = ""
        if not whitelisted:
            used_now = await get_minutes_used(user.id)
            remaining = max(0.0, FREE_MINUTES - used_now)
            balance_line = f"\n\n📊 Остаток минут: <b>{remaining:.1f}</b>"

        await status_msg.edit_text(
            f"✅ Готово! Что сделать с записью?{balance_line}",
            parse_mode="HTML",
            reply_markup=choose_mode_kb(token),
        )
        await finish_job(job_id, "done")
    except Exception as e:
        logger.exception("Post-STT delivery failed: {e}", e=e)
        await log_event(user_id=user.id, type_="error")
        await finish_job(job_id, "failed")
        await status_msg.edit_text(
            "⚠️ Расшифровка готова, но не удалось её показать. "
            "Откройте «📁 Мои записи» — она там."
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
    await _process(cb, token, action)


@router.callback_query(F.data.startswith("t:"))
async def on_template(cb: types.CallbackQuery) -> None:
    _, token, key = cb.data.split(":", 2)
    await _process(cb, token, key)


@router.callback_query(F.data.startswith("chg:"))
async def on_change_template(cb: types.CallbackQuery) -> None:
    """Обратная совместимость — старая кнопка 'Сменить шаблон'."""
    if not cb.message:
        return
    token = cb.data.split(":", 1)[1]
    if not session_store.get(token, cb.from_user.id if cb.from_user else 0):
        await _recover_session(cb)
        return
    await cb.message.edit_text("Что сделать с записью?", reply_markup=choose_mode_kb(token))
    await cb.answer()


@router.callback_query(F.data.startswith("dl:"))
async def on_download(cb: types.CallbackQuery) -> None:
    """Скачать расшифровку (только для режима 'Просто расшифровка')."""
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
        await log_event(user_id=user.id, type_="error", err_code="export_fail")
        await cb.message.answer("⚠️ Не удалось сформировать файл. Попробуйте другой формат.")


@router.callback_query(F.data.startswith("dr:"))
async def on_download_result(cb: types.CallbackQuery) -> None:
    """Скачать результат GigaChat (Самари, Роадмап, Ключевые моменты и др.)."""
    user = cb.from_user
    if not user or not cb.message:
        return
    _, token, fmt = cb.data.split(":", 2)
    entry = session_store.get(token, user.id)
    if not entry:
        await _recover_session(cb)
        return
    result_text = entry.last_result or entry.transcript
    label = TEMPLATES.get(entry.last_key or "", TEMPLATES["plain"]).label if entry.last_key else "Результат МОЛВИ"
    await cb.answer("Готовлю файл…")
    try:
        data, filename = await asyncio.to_thread(build_export, fmt, label, result_text)
        await cb.message.answer_document(
            types.BufferedInputFile(data, filename=filename),
            caption=f"📄 {label} ({fmt.upper()})",
        )
        await log_event(user_id=user.id, type_="export", fmt=fmt)
    except Exception as e:
        logger.exception("Export result failed: {e}", e=e)
        await log_event(user_id=user.id, type_="error", err_code="export_fail")
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
    await log_event(user_id=user.id, type_="as_message")
    full = _watermarked(entry.transcript)
    for part in split_telegram_text(full):
        await cb.message.answer(part)


# Защита от двойного клика: кнопка в клиенте остаётся активной до cb.answer(), и
# второй клик до него уходил вторым вызовом LLM — при одном потоке GigaChat (см.
# LLM_LANE) это убивало первый ответ.
_inflight_templates: set[tuple[int, str, str]] = set()


async def _process(cb: types.CallbackQuery, token: str, key: str) -> None:
    user = cb.from_user
    if not user or not cb.message:
        return
    entry = session_store.get(token, user.id)
    if not entry:
        await _recover_session(cb)
        return

    cached = entry.results.get(key)
    if cached is not None:
        # Уже считали этот шаблон для этой записи — отдаём из кэша мгновенно,
        # без нового вызова GigaChat и без учёта в лимите прогонов.
        await cb.answer()
        await _render(cb, token, key, cached)
        return

    inflight_key = (user.id, token, key)
    if inflight_key in _inflight_templates:
        await cb.answer("Уже обрабатываю…")
        return
    _inflight_templates.add(inflight_key)

    try:
        # cb.answer() — ДО edit_text, а не после: пока не вызван, кнопка в клиенте
        # остаётся «нажимаемой», и промедление здесь как раз и открывало двойной клик.
        await cb.answer()

        whitelisted = await is_whitelisted(user.id, user.username)
        if not whitelisted and entry.runs >= settings.template_runs_limit:
            await log_event(user_id=user.id, type_="paywall")
            await cb.message.edit_text(  # type: ignore[union-attr]
                template_limit_text(), parse_mode="HTML", reply_markup=paywall_kb()
            )
            return

        # Считаем прогон сразу — GigaChat вызывается ниже независимо от исхода
        # (ретраи with_retries могут стоить денег и при итоговой ошибке).
        session_store.bump_runs(token)

        await cb.message.edit_text("⏳ Обрабатываю через GigaChat…", reply_markup=None)  # type: ignore[union-attr]

        # ДО вызова — иначе провалившиеся попытки не считаются, и доля смены
        # шаблона (switch_pct) недосчитывает. job_id=token связывает это событие
        # с recognize/llm_call этой же записи.
        await log_event(user_id=user.id, type_="template", template=key, job_id=token)

        async def _on_llm_wait(position: int, eta: float) -> None:
            # LLM_LANE занята (один поток на физлицо у GigaChat) — честная оценка
            # ожидания вместо того, чтобы пользователь просто смотрел на "Обрабатываю…".
            try:
                await cb.message.edit_text(  # type: ignore[union-attr]
                    f"⏳ Вы {position}-й в очереди. Начну примерно через "
                    f"{int(eta)} с — напишу, как будет готово."
                )
            except Exception:
                pass

        async def _on_llm_start() -> None:
            try:
                await cb.message.edit_text("⏳ Обрабатываю через GigaChat…", reply_markup=None)  # type: ignore[union-attr]
            except Exception:
                pass

        try:
            system, prefix = build_summary_prompt(key)
            result = await with_retries(
                lambda: _llm.call(
                    text=prefix + entry.transcript, system=system,
                    on_wait=_on_llm_wait, on_start=_on_llm_start,
                    model=settings.llm_model_write or None,
                ),
                attempts=3,
                base_delay=1.0,
            )
            summary = result.text
            await log_event(
                user_id=user.id, type_="llm_call", job_id=token,
                model=result.model, tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                tokens_cached=result.tokens_cached, latency_ms=result.latency_ms,
            )
        except Exception as e:
            logger.exception("Summary failed: {e}", e=e)
            await log_event(user_id=user.id, type_="error", err_code="llm_fail")
            await cb.message.edit_text(  # type: ignore[union-attr]
                "⚠️ Не удалось обработать через GigaChat. Попробуйте ещё раз.",
                reply_markup=choose_mode_kb(token),
            )
            return

        # Кэшируем результат — по нему считать заново уже не придётся
        session_store.set_result(token, summary, key)
        await _render(cb, token, key, summary)
    finally:
        _inflight_templates.discard(inflight_key)


async def _render(cb: types.CallbackQuery, token: str, key: str, summary: str) -> None:
    """Форматирует и показывает результат шаблона. Обёрнута в try/except: раньше
    сбой здесь (например, Telegram 400 на обрезанном посреди тега HTML) оставлял
    сообщение в статусе «⏳ Обрабатываю…» навсегда — при уже оплаченном вызове GigaChat."""
    user = cb.from_user
    if not user or not cb.message:
        return
    try:
        label = TEMPLATES.get(key, TEMPLATES["plain"]).label
        label_safe = _html.escape(label)
        summary_html = md_to_html(summary)

        if key == "plain":
            # 2-3 тезиса + предложение скачать полную расшифровку
            body = (
                f"<b>{label_safe}</b>\n\n{summary_html}\n\n"
                f"📄 <b>Полная расшифровка готова — скачайте файлом:</b>"
            )
            await cb.message.edit_text(body, parse_mode="HTML", reply_markup=plain_result_kb(token))

        elif key in _FILE_KEYS:
            # Самари — отправляем файлом, в сообщении показываем превью
            try:
                data, filename = await asyncio.to_thread(build_export, "txt", label, summary)
                await cb.message.answer_document(
                    types.BufferedInputFile(data, filename=filename),
                    caption=f"📝 {label}",
                )
            except Exception as e:
                logger.exception("Summary file export failed: {e}", e=e)

            # Превью первых ~600 символов в сообщении
            preview_raw = summary[:600] + ("…" if len(summary) > 600 else "")
            preview_html = md_to_html(preview_raw)
            body = (
                f"<b>{label_safe}</b>\n\n{preview_html}\n\n"
                f"📎 <i>Полный текст — в прикреплённом файле выше. "
                f"Скачать ещё раз — кнопки ниже:</i>"
            )
            await cb.message.edit_text(body, parse_mode="HTML", reply_markup=ai_result_kb(token))

        else:
            # Роадмап, Ключевые моменты, Список задач, тематические шаблоны — текстом в том же сообщении
            header = f"<b>{label_safe}</b>\n\n"
            if len(header) + len(summary_html) <= _MSG_LIMIT:
                body = header + summary_html
            else:
                # Обрезаем безопасно по границам тегов — старый прямой срез строки
                # ломал HTML в 44,8% длинных ответов и ронял edit_text с 400
                cutoff = _MSG_LIMIT - len(header) - 80
                body = (
                    header
                    + split_html_safe(summary_html, cutoff)
                    + "\n\n<i>…текст сокращён. Скачайте полный вариант файлом 👇</i>"
                )
            await cb.message.edit_text(body, parse_mode="HTML", reply_markup=ai_result_kb(token))
    except Exception as e:
        logger.exception("Render failed: {e}", e=e)
        await log_event(user_id=user.id, type_="error")
        await cb.message.answer(
            "⚠️ Расшифровка готова, но не удалось её показать. "
            "Откройте «📁 Мои записи» — она там."
        )
