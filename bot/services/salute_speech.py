from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass

import httpx
from loguru import logger

from bot.config import settings
from bot.services.oauth import AccessToken, fetch_access_token

_PCM_CONTENT_TYPE = "audio/x-pcm;bit=16;rate=16000"


class SaluteSpeechError(RuntimeError):
    pass


class SaluteSpeechQuotaError(SaluteSpeechError):
    """Исчерпан пакет/баланс SaluteSpeech (HTTP 402). Ретраи не помогут."""
    pass


def _unwrap(data: dict) -> dict | list | str | None:
    """SaluteSpeech REST оборачивает ответы в {"status": 200, "result": ...}.

    Возвращает содержимое result, либо сам data если конверта нет.
    """
    if isinstance(data, dict) and "result" in data and "status" in data:
        return data["result"]
    return data


def _extract_sync_text(data: dict) -> str | None:
    """Текст из синхронного ответа speech:recognize.

    Формат: {"status": 200, "result": ["текст1", "текст2"], "request_id": ...}
    """
    result = _unwrap(data)

    if isinstance(result, list):
        joined = " ".join(str(r).strip() for r in result if r)
        return joined or None
    if isinstance(result, str) and result.strip():
        return result.strip()
    if isinstance(result, dict):
        return _extract_async_text(result)
    return None


def _extract_async_text(payload) -> str | None:
    """Текст из результата асинхронного распознавания (data:download).

    Формат — список фрагментов, в каждом results[].text / normalized_text.
    """
    if isinstance(payload, dict):
        payload = _unwrap(payload)

    fragments: list[str] = []

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            results = item.get("results")
            if isinstance(results, list) and results:
                first = results[0]
                if isinstance(first, dict):
                    txt = first.get("normalized_text") or first.get("text")
                    if txt:
                        fragments.append(str(txt).strip())
            elif item.get("text"):
                fragments.append(str(item["text"]).strip())
    elif isinstance(payload, dict):
        txt = payload.get("normalized_text") or payload.get("text") or payload.get("result")
        if txt:
            return str(txt).strip()
    elif isinstance(payload, str) and payload.strip():
        return payload.strip()

    joined = " ".join(f for f in fragments if f)
    return joined or None


@dataclass
class SaluteSpeechClient:
    auth_key: str
    scope: str = "SALUTE_SPEECH_PERS"
    _token: AccessToken | None = None

    async def _get_token(self) -> str:
        if self._token and self._token.is_valid():
            return self._token.token
        self._token = await fetch_access_token(auth_key=self.auth_key, scope=self.scope)
        return self._token.token

    async def recognize_short(self, pcm_path: str) -> str:
        """Синхронное распознавание (до ~1 минуты). Принимает raw PCM 16kHz mono 16-bit."""
        token = await self._get_token()
        url = "https://smartspeech.sber.ru/rest/v1/speech:recognize"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": _PCM_CONTENT_TYPE,
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
        }
        params = {"language": "ru-RU", "model": "general"}

        with open(pcm_path, "rb") as f:
            audio_bytes = f.read()

        async with httpx.AsyncClient(verify=settings.sber_verify_ssl, timeout=120) as client:
            resp = await client.post(url, headers=headers, params=params, content=audio_bytes)
            if resp.status_code == 402:
                raise SaluteSpeechQuotaError("SaluteSpeech 402: пакет распознавания исчерпан")
            if resp.status_code >= 400:
                logger.error("SaluteSpeech recognize {code}: {text}", code=resp.status_code, text=resp.text)
            resp.raise_for_status()
            data = resp.json()

        text = _extract_sync_text(data)
        if not text:
            raise SaluteSpeechError(f"Empty recognition result: {data}")
        return text

    async def recognize_long(self, pcm_path: str) -> str:
        """Асинхронный режим для длинных записей: upload → async_recognize → poll → download."""
        token = await self._get_token()
        verify = settings.sber_verify_ssl

        base_rest = "https://smartspeech.sber.ru/rest/v1"
        auth_headers = {"Authorization": f"Bearer {token}", "RqUID": str(uuid.uuid4())}

        with open(pcm_path, "rb") as f:
            audio_bytes = f.read()

        async with httpx.AsyncClient(verify=verify, timeout=300) as client:
            # 1) upload файла
            upload_resp = await client.post(
                f"{base_rest}/data:upload",
                headers={**auth_headers, "Content-Type": _PCM_CONTENT_TYPE},
                content=audio_bytes,
            )
            if upload_resp.status_code == 402:
                raise SaluteSpeechQuotaError("SaluteSpeech 402: пакет распознавания исчерпан")
            if upload_resp.status_code >= 400:
                logger.error("Upload {code}: {text}", code=upload_resp.status_code, text=upload_resp.text)
            upload_resp.raise_for_status()
            upload_result = _unwrap(upload_resp.json())
            request_file_id = None
            if isinstance(upload_result, dict):
                request_file_id = upload_result.get("request_file_id") or upload_result.get("id")
            if not request_file_id:
                raise SaluteSpeechError(f"Upload: missing request_file_id: {upload_resp.json()}")

            # 2) запуск async-распознавания (для raw PCM указываем формат явно)
            start_payload = {
                "options": {
                    "language": "ru-RU",
                    "audio_encoding": "PCM_S16LE",
                    "sample_rate": 16000,
                    "model": "general",
                },
                "request_file_id": request_file_id,
            }
            start_resp = await client.post(
                f"{base_rest}/speech:async_recognize",
                headers={**auth_headers, "Content-Type": "application/json"},
                json=start_payload,
            )
            if start_resp.status_code >= 400:
                logger.error("Async start {code}: {text}", code=start_resp.status_code, text=start_resp.text)
            start_resp.raise_for_status()
            start_result = _unwrap(start_resp.json())
            task_id = None
            if isinstance(start_result, dict):
                task_id = start_result.get("id") or start_result.get("task_id")
            if not task_id:
                raise SaluteSpeechError(f"Async start: missing task id: {start_resp.json()}")

            # 3) polling статуса задачи
            deadline = time.time() + 20 * 60
            status = None
            response_file_id = None
            while time.time() < deadline:
                poll = await client.get(
                    f"{base_rest}/task:get",
                    headers=auth_headers,
                    params={"id": task_id},
                )
                poll.raise_for_status()
                poll_result = _unwrap(poll.json())
                if isinstance(poll_result, dict):
                    status = poll_result.get("status") or poll_result.get("state")
                    if status in ("DONE", "COMPLETED", "SUCCESS"):
                        response_file_id = poll_result.get("response_file_id")
                        break
                    if status in ("ERROR", "FAILED", "CANCELED"):
                        raise SaluteSpeechError(f"Async task failed: {poll.json()}")
                await asyncio.sleep(3)

            if not response_file_id:
                raise SaluteSpeechError(
                    f"Async task timeout or missing response_file_id (status={status})"
                )

            # 4) скачивание результата
            down = await client.get(
                f"{base_rest}/data:download",
                headers=auth_headers,
                params={"response_file_id": response_file_id},
            )
            down.raise_for_status()

            content_type = down.headers.get("content-type", "")
            if "application/json" in content_type:
                text = _extract_async_text(down.json())
                if not text:
                    raise SaluteSpeechError(f"Download JSON but no text: {down.text[:500]}")
                return text

            raw = down.text.strip()
            if not raw:
                raise SaluteSpeechError("Download returned empty text")

            try:
                parsed = json.loads(raw)
                text = _extract_async_text(parsed)
                if text:
                    return text
            except Exception:
                pass

            return raw
