"""In-memory хранилище расшифровок на время сессии (Вариант А).

Контент (расшифровка) НИКОГДА не пишется на диск или в БД. Он живёт только
в оперативной памяти процесса ограниченное время — чтобы пользователь мог
сменить шаблон без повторного распознавания. По истечении TTL запись удаляется.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

DEFAULT_TTL_SEC = 24 * 3600  # 24 часа — чтобы кнопки работали в течение дня


@dataclass
class _Entry:
    user_id: int
    transcript: str
    duration_sec: int | None
    expires_at: float
    last_result: str | None = field(default=None)  # последний результат GigaChat
    last_key: str | None = field(default=None)      # ключ шаблона для last_result


class SessionStore:
    def __init__(self, ttl_sec: int = DEFAULT_TTL_SEC) -> None:
        self._ttl = ttl_sec
        self._data: dict[str, _Entry] = {}

    def put(self, user_id: int, transcript: str, duration_sec: int | None) -> str:
        self._gc()
        token = uuid.uuid4().hex[:12]
        self._data[token] = _Entry(
            user_id=user_id,
            transcript=transcript,
            duration_sec=duration_sec,
            expires_at=time.time() + self._ttl,
        )
        return token

    def get(self, token: str, user_id: int) -> _Entry | None:
        self._gc()
        entry = self._data.get(token)
        if not entry or entry.user_id != user_id:
            return None
        if entry.expires_at < time.time():
            self._data.pop(token, None)
            return None
        return entry

    def set_result(self, token: str, result: str, key: str) -> None:
        """Сохраняет последний результат GigaChat для скачивания."""
        entry = self._data.get(token)
        if entry:
            entry.last_result = result
            entry.last_key = key

    def drop(self, token: str) -> None:
        self._data.pop(token, None)

    def _gc(self) -> None:
        now = time.time()
        expired = [k for k, v in self._data.items() if v.expires_at < now]
        for k in expired:
            self._data.pop(k, None)


# Единый экземпляр на процесс.
session_store = SessionStore()
