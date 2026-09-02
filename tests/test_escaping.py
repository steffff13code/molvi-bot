"""HTML-экранирование пользовательских данных в сообщениях (PR-7): first_name
из Telegram без экранирования ломал parse_mode=HTML — пользователь с именем
«<3» не мог пройти /start вообще, и это нигде не логировалось."""
from __future__ import annotations

import html

from bot.handlers.records import _render_records_list
from bot.handlers.start import _welcome

_HOSTILE_NAMES = ["<3", "A > B", "Rock & Roll", "<script>alert(1)</script>"]


def test_welcome_escapes_hostile_names() -> None:
    for name in _HOSTILE_NAMES:
        text = _welcome(name)
        assert html.escape(name) in text
        assert "<script>alert(1)</script>" not in text


def test_welcome_still_contains_static_markup() -> None:
    # Экранирование имени не должно портить собственную разметку сообщения.
    text = _welcome("друг")
    assert "<b>МОЛВИ</b>" in text
    assert '<a href="https://molvi-ai.ru/">molvi-ai.ru</a>' in text


def test_records_preview_escapes_hostile_transcript() -> None:
    records = [{
        "id": 1,
        "duration_sec": 65,
        "transcript": "<script>alert(1)</script> обычный текст записи",
        "template": None,
        "created_at": "2026-01-01 12:00:00",
    }]
    text, _kb = _render_records_list(records)
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text
