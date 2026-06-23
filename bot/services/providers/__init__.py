"""Слой-адаптер провайдеров (swap-ready). См. PROVIDER.md.

Весь остальной код вызывает ТОЛЬКО get_stt()/get_llm(), не зная конкретного
провайдера. Замена провайдера = новая реализация здесь + переменные .env,
без правок в шаблонах/UX/лимитах.
"""

from bot.services.providers.llm import LLMProvider, get_llm
from bot.services.providers.stt import STTProvider, STTQuotaError, get_stt

__all__ = ["STTProvider", "STTQuotaError", "get_stt", "LLMProvider", "get_llm"]
