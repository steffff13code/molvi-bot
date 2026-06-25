from __future__ import annotations

import asyncio
import os

from pydub import AudioSegment

from bot.config import BASE_DIR

AUDIO_DIR = BASE_DIR / "audio"


def ensure_dirs() -> None:
    AUDIO_DIR.mkdir(exist_ok=True)


def _sync_convert_to_pcm(input_path: str, output_path: str) -> None:
    """Конвертирует аудио в raw PCM 16kHz mono 16-bit (без заголовка WAV)."""
    audio = AudioSegment.from_file(input_path)
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    with open(output_path, "wb") as f:
        f.write(audio.raw_data)


async def convert_to_pcm(input_path: str, output_path: str) -> None:
    """Асинхронная обёртка над синхронным pydub чтобы не блокировать event loop."""
    await asyncio.to_thread(_sync_convert_to_pcm, input_path, output_path)


# Алиас для обратной совместимости с voice.py
convert_to_wav = convert_to_pcm


def _sync_trim(input_path: str, output_path: str, max_sec: int) -> int:
    """Обрезает аудио до max_sec секунд. Возвращает итоговую длительность в секундах."""
    audio = AudioSegment.from_file(input_path)
    actual_sec = len(audio) // 1000
    if actual_sec <= max_sec:
        # Файл короче лимита — обрезка не нужна
        return actual_sec
    trimmed = audio[: max_sec * 1000]
    ext = os.path.splitext(output_path)[1].lstrip(".") or "mp3"
    if ext in ("oga", "opus"):
        ext = "ogg"
    trimmed.export(output_path, format=ext)
    return max_sec


async def trim_audio(input_path: str, output_path: str, max_sec: int) -> int:
    """Асинхронная обёртка: обрезает input_path до max_sec сек, сохраняет в output_path.

    Возвращает итоговую длительность (≤ max_sec).
    Если обрезка не нужна — возвращает реальную длительность, output_path не создаётся.
    """
    return await asyncio.to_thread(_sync_trim, input_path, output_path, max_sec)
