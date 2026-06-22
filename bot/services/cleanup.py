from __future__ import annotations

import asyncio
import time

from loguru import logger

from bot.services.audio import AUDIO_DIR


def _cleanup_audio_dir(max_age_sec: int = 3600) -> None:
    if not AUDIO_DIR.is_dir():
        return
    now = time.time()
    removed = 0
    for path in AUDIO_DIR.iterdir():
        try:
            if now - path.stat().st_mtime > max_age_sec:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            continue
        except Exception as e:
            logger.warning("Cleanup: failed to remove {path}: {e}", path=path, e=e)
    if removed:
        logger.info("Cleanup: removed {n} old files", n=removed)


async def _cleanup_loop() -> None:
    AUDIO_DIR.mkdir(exist_ok=True)
    while True:
        try:
            _cleanup_audio_dir()
        except Exception as e:
            logger.warning("Cleanup loop error: {e}", e=e)
        await asyncio.sleep(3600)


def start_cleanup_task() -> None:
    asyncio.create_task(_cleanup_loop())
