"""LLM-адаптер: текст + системный промпт → саммари. Выбор через env LLM_PROVIDER."""

from __future__ import annotations

from typing import Protocol

from bot.config import settings
from bot.services.gigachat import GigaChatClient, LLMResult


class LLMProvider(Protocol):
    async def summarize(self, *, text: str, system: str) -> str: ...
    async def call(self, *, text: str, system: str) -> LLMResult: ...


class GigaChatLLM:
    def __init__(self) -> None:
        self._client = GigaChatClient(
            auth_key=settings.gigachat_auth_key,
            scope=settings.gigachat_scope,
            model=settings.gigachat_model,
        )

    async def call(self, *, text: str, system: str) -> LLMResult:
        # v3: точность важнее креатива (temp 0.2); подробное summary требует запаса токенов.
        return await self._client.call(
            system=system, user=text, temperature=0.2, max_tokens=3500
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
