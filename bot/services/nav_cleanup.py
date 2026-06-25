"""Трекер транзитных навигационных сообщений.

Сообщения, добавленные через track(), удаляются при следующем вызове clean().
Используется чтобы убрать старые «тарифы», «помощь», «записи» когда пользователь
отправляет новое аудио.
"""
from __future__ import annotations


class NavCleanup:
    def __init__(self) -> None:
        self._msgs: dict[int, list[int]] = {}  # user_id → msg_ids

    def track(self, user_id: int, msg_id: int) -> None:
        self._msgs.setdefault(user_id, []).append(msg_id)

    async def clean(self, user_id: int, chat_id: int, bot) -> None:
        ids = self._msgs.pop(user_id, [])
        for mid in ids:
            try:
                await bot.delete_message(chat_id, mid)
            except Exception:
                pass


nav_cleanup = NavCleanup()
