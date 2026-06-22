from __future__ import annotations

import asyncio

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
