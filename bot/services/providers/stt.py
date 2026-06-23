"""STT-адаптер: аудиофайл → текст. Провайдер выбирается через env STT_PROVIDER.

Интерфейс: transcribe(source_path, duration_sec) -> str, где source_path —
ИСХОДНЫЙ скачанный файл (mp3/ogg/mp4/...). Каждый провайдер сам решает,
нужна ли ему конвертация.
"""

from __future__ import annotations

import os
import uuid
from typing import Protocol

import httpx
from loguru import logger

from bot.config import settings
from bot.services.salute_speech import SaluteSpeechClient, SaluteSpeechError, SaluteSpeechQuotaError


class STTQuotaError(SaluteSpeechError):
    """Исчерпан пакет/баланс STT-провайдера (ретраи не помогут)."""


class STTError(RuntimeError):
    pass


class STTProvider(Protocol):
    async def transcribe(self, source_path: str, duration_sec: int | None) -> str: ...


# ───────────────────────── Nexara (Whisper-совместимый) ─────────────────────────

_MIME_BY_EXT = {
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "video/mp4", ".mov": "video/quicktime",
    ".wav": "audio/wav", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
    ".webm": "audio/webm", ".flac": "audio/flac", ".aac": "audio/aac", ".amr": "audio/amr",
    ".mkv": "video/x-matroska", ".avi": "video/x-msvideo", ".3gp": "video/3gpp", ".m4v": "video/mp4",
}


class NexaraSTT:
    """Отправляет файл напрямую в Nexara (multipart). Конвертация не нужна."""

    def __init__(self) -> None:
        self._key = settings.nexara_api_key
        self._url = settings.nexara_url

    async def transcribe(self, source_path: str, duration_sec: int | None) -> str:
        if not self._key:
            raise STTError("NEXARA_API_KEY не задан")

        with open(source_path, "rb") as f:
            audio_bytes = f.read()

        ext = os.path.splitext(source_path)[1].lower()
        mime = _MIME_BY_EXT.get(ext, "application/octet-stream")
        filename = f"audio{ext or '.mp3'}"

        headers = {"Authorization": f"Bearer {self._key}"}
        files = {"file": (filename, audio_bytes, mime)}
        # json (а не verbose_json) — без посегментных данных, ответ легче/быстрее.
        data = {"response_format": "json", "language": "ru"}

        async with httpx.AsyncClient(verify=settings.sber_verify_ssl, timeout=600) as client:
            resp = await client.post(self._url, headers=headers, files=files, data=data)
            if resp.status_code in (402, 429):
                raise STTQuotaError(f"Nexara {resp.status_code}: пакет/лимит исчерпан")
            if resp.status_code >= 400:
                logger.error("Nexara error {code}: {text}", code=resp.status_code, text=resp.text[:500])
            resp.raise_for_status()
            payload = resp.json()

        text = (payload.get("text") if isinstance(payload, dict) else None) or ""
        text = text.strip()
        if not text:
            raise STTError(f"Nexara: пустой результат: {str(payload)[:300]}")
        return text


# ───────────────────────── SaluteSpeech (резервный) ─────────────────────────

class SaluteSTT:
    """Обёртка над SaluteSpeech. Требует raw PCM, поэтому конвертирует сам."""

    def __init__(self) -> None:
        self._client = SaluteSpeechClient(
            auth_key=settings.salutespeech_auth_key,
            scope=settings.salutespeech_scope,
        )

    async def transcribe(self, source_path: str, duration_sec: int | None) -> str:
        from bot.services.audio import AUDIO_DIR, convert_to_wav

        pcm_path = str(AUDIO_DIR / f"{uuid.uuid4().hex}.pcm")
        try:
            await convert_to_wav(source_path, pcm_path)
            if duration_sec is None or duration_sec <= 55:
                try:
                    return await self._client.recognize_short(pcm_path)
                except STTQuotaError:
                    raise
                except Exception as e:
                    logger.warning("Short recognize failed, fallback to long: {e}", e=e)
                    return await self._client.recognize_long(pcm_path)
            return await self._client.recognize_long(pcm_path)
        finally:
            try:
                if os.path.exists(pcm_path):
                    os.remove(pcm_path)
            except Exception:
                pass


def get_stt() -> STTProvider:
    provider = (settings.stt_provider or "nexara").lower()
    if provider == "nexara":
        return NexaraSTT()
    if provider == "salute":
        return SaluteSTT()
    raise RuntimeError(f"Неизвестный STT_PROVIDER: {provider}")
