from __future__ import annotations

import sys

from loguru import logger

from bot.config import BASE_DIR


def setup_logging() -> None:
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.remove()
    # Под pythonw.exe (фоновый запуск без консоли) sys.stderr == None — пропускаем консольный вывод.
    if sys.stderr is not None:
        logger.add(sys.stderr, level="INFO")
    logger.add(
        str(log_dir / "molvi.log"),
        level="INFO",
        rotation="10 MB",
        retention="7 days",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )
