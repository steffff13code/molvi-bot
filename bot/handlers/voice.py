from __future__ import annotations

import os
import uuid

from aiogram import Bot, Router, types
from loguru import logger

from bot.config import settings
from bot.db.queries import create_record, upsert_user
from bot.keyboards.inline import record_actions_kb
from bot.keyboards.reply import main_menu_kb
from bot.services.audio import AUDIO_DIR, convert_to_wav, ensure_dirs
from bot.services.retry import with_retries
from bot.services.salute_speech import SaluteSpeechClient, SaluteSpeechQuotaError

router = Router()

salute_client = SaluteSpeechClient(
    auth_key=settings.salutespeech_auth_key,
    scope=settings.salutespeech_scope,
)

# Поддерживаемые расширения для документов (на случай, если файл прислали «файлом»).
_SUPPORTED_DOC_EXTS = {
    ".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac", ".opus", ".wma", ".amr",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp",
}


def _ext_from_name(name: str | None) -> str:
    if not name:
        return ""
    _, ext = os.path.splitext(name)
    return ext.lower()


def _is_supported_document(doc: types.Document) -> bool:
    """Проверяет, что документ — аудио/видео (по mime или расширению)."""
    mime = (doc.mime_type or "").lower()
    if mime.startswith("audio/") or mime.startswith("video/"):
        return True
    return _ext_from_name(doc.file_name) in _SUPPORTED_DOC_EXTS


@router.message(lambda m: bool(m.voice or m.audio or m.document or m.video or m.video_note))
async def handle_audio(message: types.Message, bot: Bot) -> None:
    ensure_dirs()

    user = message.from_user
    if not user:
        return

    await upsert_user(user_id=user.id, username=user.username, first_name=user.first_name)

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

    if file_size is not None and file_size > settings.max_audio_mb * 1024 * 1024:
        await message.answer(
            f"Файл слишком большой. Лимит {settings.max_audio_mb} МБ. В следующих версиях поднимем лимит.",
            reply_markup=main_menu_kb(),
        )
        return

    if duration_sec is not None and duration_sec > settings.max_duration_sec:
        await message.answer(
            f"Запись слишком длинная. Лимит {settings.max_duration_sec // 60} мин.",
            reply_markup=main_menu_kb(),
        )
        return

    dur_text = f" ({duration_sec} сек)" if duration_sec else ""
    status_msg = await message.answer(f"🎧 Принял запись{dur_text}. Расшифровываю…")

    uid = uuid.uuid4().hex
    source_path = str(AUDIO_DIR / f"{uid}_src{_ext_from_name(file_name) or ''}")
    pcm_path = str(AUDIO_DIR / f"{uid}.pcm")

    try:
        tg_file = await bot.get_file(tg_file_id)  # type: ignore[arg-type]

        await bot.download_file(tg_file.file_path, destination=source_path)  # type: ignore[attr-defined]

        await convert_to_wav(source_path, pcm_path)

        async def _recognize() -> str:
            if duration_sec is None or duration_sec <= 55:
                try:
                    return await salute_client.recognize_short(pcm_path)
                except SaluteSpeechQuotaError:
                    raise  # квота — фолбэк на long не поможет
                except Exception as e:
                    logger.warning("Short recognize failed, fallback to long: {e}", e=e)
                    return await salute_client.recognize_long(pcm_path)
            return await salute_client.recognize_long(pcm_path)

        transcript = await with_retries(_recognize, attempts=3, base_delay=2.0)

        record_id = await create_record(
            user_id=user.id,
            tg_file_id=tg_file_id,
            duration_sec=duration_sec,
            transcript=transcript,
        )

        await status_msg.edit_text(
            "✅ Готово! Что сделать с записью?",
            reply_markup=record_actions_kb(record_id),
        )
    except SaluteSpeechQuotaError:
        logger.error("SaluteSpeech quota exhausted (402)")
        await status_msg.edit_text(
            "⚠️ Сервис распознавания временно недоступен (исчерпан пакет SaluteSpeech). "
            "Мы уже пополняем баланс — попробуйте чуть позже."
        )
    except Exception as e:
        logger.exception("Voice handler failed: {e}", e=e)
        await status_msg.edit_text(
            "⚠️ Не удалось расшифровать запись. Попробуйте ещё раз через минуту."
        )
    finally:
        for path in (source_path, pcm_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
