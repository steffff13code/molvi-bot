from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from loguru import logger

from bot.config import sber_verify
from bot.services.oauth import AccessToken, fetch_access_token


class GigaChatError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    tokens_cached: int
    latency_ms: int
    finish_reason: str


@dataclass
class GigaChatClient:
    auth_key: str
    scope: str = "GIGACHAT_API_PERS"
    model: str = "GigaChat-2-Pro"
    _token: AccessToken | None = None

    async def _get_token(self) -> str:
        if self._token and self._token.is_valid():
            return self._token.token
        self._token = await fetch_access_token(auth_key=self.auth_key, scope=self.scope)
        return self._token.token

    async def call(self, *, system: str, user: str, temperature: float = 0.3, max_tokens: int = 2000) -> LLMResult:
        token = await self._get_token()
        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # 60с общего таймаута не хватает на генерацию 3500 токенов на длинных
        # записях — это и есть источник лишних ретраев, которые упомянуты в PR-6.
        timeout = httpx.Timeout(connect=10, read=180, write=60, pool=10)
        start = time.monotonic()
        async with httpx.AsyncClient(verify=sber_verify(), timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                logger.error("GigaChat error {code}: {text}", code=resp.status_code, text=resp.text)
            resp.raise_for_status()
            data = resp.json()
        latency_ms = int((time.monotonic() - start) * 1000)

        try:
            choice = data["choices"][0]
            text = str(choice["message"]["content"]).strip()
        except Exception as e:
            raise GigaChatError(f"Unexpected response format: {data}") from e

        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            model=str(data.get("model") or self.model),
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            tokens_cached=int(usage.get("precached_prompt_tokens") or 0),
            latency_ms=latency_ms,
            finish_reason=str(choice.get("finish_reason") or ""),
        )

