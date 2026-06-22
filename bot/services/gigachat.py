from __future__ import annotations

from dataclasses import dataclass

import httpx
from loguru import logger

from bot.config import settings
from bot.services.oauth import AccessToken, fetch_access_token


class GigaChatError(RuntimeError):
    pass


@dataclass
class GigaChatClient:
    auth_key: str
    scope: str = "GIGACHAT_API_PERS"
    model: str = "GigaChat"
    _token: AccessToken | None = None

    async def _get_token(self) -> str:
        if self._token and self._token.is_valid():
            return self._token.token
        self._token = await fetch_access_token(auth_key=self.auth_key, scope=self.scope)
        return self._token.token

    async def complete(self, *, system: str, user: str, temperature: float = 0.3, max_tokens: int = 2000) -> str:
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

        async with httpx.AsyncClient(verify=settings.sber_verify_ssl, timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                logger.error("GigaChat error {code}: {text}", code=resp.status_code, text=resp.text)
            resp.raise_for_status()
            data = resp.json()

        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except Exception as e:
            raise GigaChatError(f"Unexpected response format: {data}") from e

