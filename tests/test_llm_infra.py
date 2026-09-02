"""LLM-инфраструктура (PR-16): настраиваемый base_url (без него GigaChat 3 Ultra
недоступен физически — с 16.07.2026 единый адрес api.giga.chat), модель как
аргумент вызова (а не только поле клиента — нужно для замеров PR-17 без релиза),
response_format прокидывается только когда его действительно передали."""
from __future__ import annotations

import httpx
import respx

from bot.prompts.system_prompts import COMMON_RULE, WRITE_STYLE_RULE, build_summary_prompt
from bot.services.gigachat import GigaChatClient

_OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"


def _mock_oauth(router: respx.MockRouter) -> None:
    router.post(_OAUTH_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
    )


def _chat_response(model: str = "GigaChat-2-Pro") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [{"message": {"content": "готово"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "precached_prompt_tokens": 0},
        },
    )


@respx.mock
async def test_call_uses_configured_base_url() -> None:
    _mock_oauth(respx.mock)
    route = respx.post("https://custom.example/api/v1/chat/completions").mock(
        return_value=_chat_response()
    )
    client = GigaChatClient(auth_key="k", base_url="https://custom.example")

    result = await client.call(system="s", user="u")

    assert route.called
    assert result.text == "готово"


@respx.mock
async def test_call_model_argument_overrides_client_default() -> None:
    _mock_oauth(respx.mock)
    route = respx.post("https://api.giga.chat/api/v1/chat/completions").mock(
        return_value=_chat_response(model="GigaChat-3-Ultra")
    )
    client = GigaChatClient(auth_key="k", model="GigaChat-2-Pro")

    result = await client.call(system="s", user="u", model="GigaChat-3-Ultra")

    sent = route.calls.last.request
    import json
    body = json.loads(sent.content)
    assert body["model"] == "GigaChat-3-Ultra"
    assert result.model == "GigaChat-3-Ultra"


@respx.mock
async def test_call_without_model_argument_uses_client_default() -> None:
    _mock_oauth(respx.mock)
    route = respx.post("https://api.giga.chat/api/v1/chat/completions").mock(
        return_value=_chat_response()
    )
    client = GigaChatClient(auth_key="k", model="GigaChat-2-Pro")

    await client.call(system="s", user="u")

    import json
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "GigaChat-2-Pro"


@respx.mock
async def test_response_format_omitted_by_default() -> None:
    _mock_oauth(respx.mock)
    route = respx.post("https://api.giga.chat/api/v1/chat/completions").mock(
        return_value=_chat_response()
    )
    client = GigaChatClient(auth_key="k")

    await client.call(system="s", user="u")

    import json
    body = json.loads(route.calls.last.request.content)
    assert "response_format" not in body


@respx.mock
async def test_response_format_passed_through_when_given() -> None:
    _mock_oauth(respx.mock)
    route = respx.post("https://api.giga.chat/api/v1/chat/completions").mock(
        return_value=_chat_response()
    )
    client = GigaChatClient(auth_key="k")
    schema = {"type": "json_schema", "json_schema": {"name": "x", "strict": True}}

    await client.call(system="s", user="u", response_format=schema)

    import json
    body = json.loads(route.calls.last.request.content)
    assert body["response_format"] == schema


@respx.mock
async def test_user_agent_header_present() -> None:
    _mock_oauth(respx.mock)
    route = respx.post("https://api.giga.chat/api/v1/chat/completions").mock(
        return_value=_chat_response()
    )
    client = GigaChatClient(auth_key="k")

    await client.call(system="s", user="u")

    assert route.calls.last.request.headers["user-agent"] == "molvi-bot/1.0"


# ───────────────────────── COMMON_RULE v4 / WRITE_STYLE_RULE ─────────────────────────

def test_common_rule_v4_drops_hidden_reasoning_instruction() -> None:
    # Ключевая находка аудита: просьба "мысленно перечитай... сам разбор не выводи"
    # ломает слабую модель — в v4 её быть не должно.
    assert "сам разбор не выводи" not in COMMON_RULE
    assert "не копируй" not in COMMON_RULE


def test_common_rule_v4_ends_with_russian_requirement() -> None:
    assert "Отвечай по-русски" in COMMON_RULE


def test_write_style_rule_carries_formatting() -> None:
    assert "жирным" in WRITE_STYLE_RULE
    assert "телеграфным" in WRITE_STYLE_RULE


def test_build_summary_prompt_includes_both_rule_blocks() -> None:
    system, prefix = build_summary_prompt("plain")
    assert COMMON_RULE in system
    assert WRITE_STYLE_RULE in system
    assert prefix == "Расшифровка:\n"
