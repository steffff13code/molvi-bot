"""LLM-адаптер: текст + системный промпт → саммари. Выбор через env LLM_PROVIDER."""

from __future__ import annotations

from typing import Protocol

from bot.config import settings
from bot.services.gigachat import GigaChatClient


class LLMProvider(Protocol):
    async def summarize(self, *, text: str, system: str) -> str: ...


class GigaChatLLM:
    def __init__(self) -> None:
        self._client = GigaChatClient(
            auth_key=settings.gigachat_auth_key,
            scope=settings.gigachat_scope,
            model=settings.gigachat_model,
        )

    async def summarize(self, *, text: str, system: str) -> str:
        return await self._client.complete(system=system, user=text)


def get_llm() -> LLMProvider:
    provider = (settings.llm_provider or "gigachat").lower()
    if provider == "gigachat":
        return GigaChatLLM()
    raise RuntimeError(f"Неизвестный LLM_PROVIDER: {provider}")
