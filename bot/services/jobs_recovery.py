"""Надёжность-2 (PR-20): при старте поднимает задачи, «осиротевшие» из-за
падения/рестарта процесса посреди STT (bot/handlers/voice.py:create_job()).

Реального возобновления обработки здесь нет — Telegram-контекст (сообщение,
callback) конкретного апдейта не переживает рестарт процесса физически. Вместо
этого — единственное, что можно сделать безопасно и честно: сообщить
пользователю, что произошло, и направить в «Мои записи» вместо вечного «⏳»,
чтобы он не прислал файл повторно и не заплатил за одну и ту же запись дважды
(save_record() пишет расшифровку в БД раньше, чем add_minutes() её списывает —
велика вероятность, что результат уже там).
"""

from __future__ import annotations

from aiogram import Bot
from loguru import logger

from bot.db.queries import finish_job, get_stalled_jobs

_RECOGNIZE_TEXT = (
    "⚠️ Бот перезапускался во время обработки вашей последней записи.\n\n"
    "Проверьте «📁 Мои записи» — если расшифровка уже там, присылать файл "
    "заново не нужно. Если записи нет — пришлите его ещё раз."
)


async def notify_stalled_jobs(bot: Bot) -> None:
    stalled = await get_stalled_jobs()
    if not stalled:
        return
    logger.warning("jobs_recovery: найдено {n} задач в 'processing' после рестарта", n=len(stalled))
    for job in stalled:
        if job["kind"] == "recognize":
            try:
                await bot.send_message(job["user_id"], _RECOGNIZE_TEXT)
            except Exception as e:
                # Пользователь мог заблокировать бота — это не повод не закрыть job.
                logger.warning(
                    "jobs_recovery: не удалось уведомить user_id={uid}: {e}",
                    uid=job["user_id"], e=e,
                )
        # Закрываем терминально в любом случае — иначе при каждом следующем
        # рестарте будем слать это же уведомление снова и снова.
        await finish_job(job["id"], "failed")
