from __future__ import annotations

import asyncio

from loguru import logger

from bot.config import BASE_DIR
from bot.services.concurrency import FFMPEG_LANE

AUDIO_DIR = BASE_DIR / "audio"


def ensure_dirs() -> None:
    AUDIO_DIR.mkdir(exist_ok=True)


async def probe_duration(path: str) -> int | None:
    """Длительность файла через ffprobe. Возвращает None, если определить не удалось."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        return None
    try:
        return int(float(out.decode().strip()))
    except (ValueError, AttributeError):
        return None


def _sync_convert_to_pcm(input_path: str, output_path: str) -> None:
    """Конвертирует аудио в raw PCM 16kHz mono 16-bit (без заголовка WAV)."""
    from pydub import AudioSegment  # локальный импорт: нужен только SaluteSTT (легаси)

    audio = AudioSegment.from_file(input_path)
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    with open(output_path, "wb") as f:
        f.write(audio.raw_data)


async def convert_to_pcm(input_path: str, output_path: str) -> None:
    """Асинхронная обёртка над синхронным pydub, чтобы не блокировать event loop.

    Нужна только резервному SaluteSTT (не горячий путь, STT_PROVIDER=nexara по
    умолчанию) — грузить весь файл в память тут не проблема, в отличие от trim_audio.
    """
    await asyncio.to_thread(_sync_convert_to_pcm, input_path, output_path)


# Алиас для обратной совместимости с voice.py
convert_to_wav = convert_to_pcm


async def _ffmpeg_run(*args: str) -> tuple[int, bytes]:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-y", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=180)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return proc.returncode or 0, err


async def _reencode_trim(input_path: str, output_path: str, max_sec: int) -> None:
    # Без явного -c:a — ffmpeg сам выбирает кодек по расширению output_path.
    # Проверено на всех 11 форматах voice.py: жёстко заданный кодек (например,
    # всегда libopus) не пишется в чужой контейнер (например, .flac) и падает.
    rc, err = await _ffmpeg_run("-i", input_path, "-t", str(max_sec), output_path)
    if rc != 0:
        raise RuntimeError(f"ffmpeg trim failed (перекодирование): {err.decode(errors='replace')[-300:]!r}")


async def _run_ffmpeg_trim(input_path: str, output_path: str, max_sec: int) -> None:
    rc, err = await _ffmpeg_run("-i", input_path, "-t", str(max_sec), "-c", "copy", output_path)

    if rc == 0:
        # -c copy не всегда честен: например, у FLAC итоговый файл может остаться
        # с длительностью исходника в заголовке (STREAMINFO не пересчитывается),
        # хотя сам поток усечён верно. Перепроверяем результат — если метаданные
        # не сходятся, это не ложная тревога, а реальный риск перебилинга.
        out_dur = await probe_duration(output_path)
        if out_dur is None or out_dur <= max_sec + 3:
            return
        logger.warning(
            "ffmpeg -c copy trim дал файл с недостоверной длительностью "
            "({out_dur} > {max_sec}) — перекодирую", out_dur=out_dur, max_sec=max_sec,
        )
    else:
        # -c copy не режет не на keyframe для всех контейнеров — фолбэк с
        # перекодированием, медленнее, но память всё равно O(1) (потоковая
        # обработка, не загрузка в RAM).
        logger.warning(
            "ffmpeg -c copy trim failed (rc={rc}): {err} — перекодирую",
            rc=rc, err=err.decode(errors="replace")[-300:],
        )

    await _reencode_trim(input_path, output_path, max_sec)


async def trim_audio(input_path: str, output_path: str, max_sec: int) -> int:
    """Обрезает input_path до max_sec сек без декодирования в память (ffmpeg -c copy),
    сохраняет в output_path. Возвращает итоговую длительность (≤ max_sec).

    Если обрезка не нужна — возвращает реальную длительность, output_path не создаётся.
    """
    dur = await probe_duration(input_path)
    if dur is not None and dur <= max_sec:
        return dur
    await FFMPEG_LANE.run(lambda: _run_ffmpeg_trim(input_path, output_path, max_sec))
    return max_sec
