"""LLM-адаптер: текст + системный промпт → саммари. Выбор через env LLM_PROVIDER."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from bot.config import settings
from bot.services.concurrency import LLM_LANE
from bot.services.gigachat import GigaChatClient, LLMResult

OnWait = Callable[[int, float], Awaitable[None]]
OnStart = Callable[[], Awaitable[None]]


class LLMProvider(Protocol):
    async def summarize(self, *, text: str, system: str) -> str: ...
    async def call(
        self, *, text: str, system: str, on_wait: OnWait | None = None, on_start: OnStart | None = None,
    ) -> LLMResult: ...


class GigaChatLLM:
    def __init__(self) -> None:
        self._client = GigaChatClient(
            auth_key=settings.gigachat_auth_key,
            scope=settings.gigachat_scope,
            model=settings.gigachat_model,
        )

    async def call(
        self, *, text: str, system: str, on_wait: OnWait | None = None, on_start: OnStart | None = None,
    ) -> LLMResult:
        # Захват на границе провайдера (а не в хендлере) — разрешение освобождается
        # на паузах между ретраями, и будущие проходы конвейера (PR-18) покрываются
        # автоматически. v3: точность важнее креатива (temp 0.2); подробное summary
        # требует запаса токенов.
        return await LLM_LANE.run(
            lambda: self._client.call(system=system, user=text, temperature=0.2, max_tokens=3500),
            on_wait=on_wait,
            on_start=on_start,
        )

    async def summarize(self, *, text: str, system: str) -> str:
        """Совместимость: только текст, без метрик расхода токенов.
        Полная новая сигнатура для вызывающего кода — в PR-16."""
        result = await self.call(text=text, system=system)
        return result.text


def get_llm() -> LLMProvider:
    provider = (settings.llm_provider or "gigachat").lower()
    if provider == "gigachat":
        return GigaChatLLM()
    raise RuntimeError(f"Неизвестный LLM_PROVIDER: {provider}")
