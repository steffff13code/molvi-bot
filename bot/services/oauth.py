from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import httpx

from bot.config import settings


@dataclass
class AccessToken:
    token: str
    expires_at: float

    def is_valid(self, skew_sec: int = 30) -> bool:
        return time.time() < (self.expires_at - skew_sec)


async def fetch_access_token(*, auth_key: str, scope: str) -> AccessToken:
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
        "Authorization": f"Basic {auth_key}",
    }
    data = {"scope": scope}

    async with httpx.AsyncClient(verify=settings.sber_verify_ssl, timeout=30) as client:
        resp = await client.post(url, headers=headers, data=data)
        resp.raise_for_status()
        payload = resp.json()

    token = payload.get("access_token")
    expires_in = int(payload.get("expires_in", 1800))
    if not token:
        raise RuntimeError(f"OAuth: no access_token in response: {payload}")

    return AccessToken(token=str(token), expires_at=time.time() + expires_in)

