"""In-memory кэш активной сессии (быстрый повтор шаблона без нового распознавания).

Это НЕ единственное хранилище контента: save_record() отдельно пишет полный
текст расшифровки в records (см. bot/db/queries.py) — иначе пользователь терял
бы оплаченный результат при каждом рестарте Railway (session_store живёт в RAM
процесса и не переживает рестарт). records хранится records_retention_days
дней (по умолчанию 30) и удаляется раньше командой /forget — см. PR-7.

Сама структура ниже — TTL-кэш: живёт ограниченное время в памяти процесса и
не пишется на диск сама по себе; по истечении TTL запись удаляется.
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
    results: dict[str, str] = field(default_factory=dict)  # ключ шаблона → готовый текст (кэш)
    runs: int = 0                                            # сколько РАЗНЫХ шаблонов прогнано
    last_key: str | None = field(default=None)               # ключ последнего прогнанного шаблона

    @property
    def last_result(self) -> str | None:
        """Совместимость: результат последнего прогнанного шаблона."""
        return self.results.get(self.last_key or "")


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
        """Кэширует результат конкретного шаблона и запоминает его как последний —
        для 'скачать результат ещё раз' и мгновенной отдачи при повторном нажатии."""
        entry = self._data.get(token)
        if entry:
            entry.results[key] = result
            entry.last_key = key

    def get_result(self, token: str, key: str) -> str | None:
        """Кэшированный результат конкретного шаблона, если он уже считался."""
        entry = self._data.get(token)
        return entry.results.get(key) if entry else None

    def bump_runs(self, token: str) -> int:
        """Учитывает ещё один РАЗНЫЙ прогон шаблона (не из кэша). Возвращает новое значение."""
        entry = self._data.get(token)
        if not entry:
            return 0
        entry.runs += 1
        return entry.runs

    def drop(self, token: str) -> None:
        self._data.pop(token, None)

    def _gc(self) -> None:
        now = time.time()
        expired = [k for k, v in self._data.items() if v.expires_at < now]
        for k in expired:
            self._data.pop(k, None)


# Единый экземпляр на процесс.
session_store = SessionStore()
