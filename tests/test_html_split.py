"""split_html_safe() не должна ломать HTML при обрезке (аудит: 44,8% длинных ответов
падали в Telegram с ошибкой 400 из-за среза summary_html[:cutoff] посреди тега)."""
from __future__ import annotations

import random
import re

from bot.utils import md_to_html, split_html_safe

_WORDS = [
    "Отчёт", "задача", "решение", "клиент", "встреча", "результат", "план", "бюджет",
    "команда", "проект", "звонок", "документ", "сделка", "продукт", "статус", "срок",
]


def _random_markdown(rng: random.Random) -> str:
    lines = []
    for _ in range(rng.randint(5, 40)):
        words = " ".join(rng.choice(_WORDS) for _ in range(rng.randint(3, 12)))
        kind = rng.random()
        if kind < 0.15:
            lines.append(f"## {words}")
        elif kind < 0.3:
            lines.append(f"**{words}**")
        elif kind < 0.45:
            lines.append(f"- {words}")
        elif kind < 0.55:
            lines.append(f"Цель: {words}")
        else:
            lines.append(words + rng.choice([".", "!", "?", ""]))
    return "\n".join(lines)


def test_split_html_safe_never_breaks_tags_or_entities() -> None:
    rng = random.Random(42)
    for _ in range(100):
        html = md_to_html(_random_markdown(rng))
        if not html:
            continue
        cutoff = rng.randint(1, len(html))
        result = split_html_safe(html, cutoff)

        assert result.count("<b>") == result.count("</b>"), (cutoff, html, result)
        assert not re.search(r"<[^>]*$", result), result
        assert not re.search(r"&[a-zA-Z#][a-zA-Z0-9#]*$", result), result


def test_split_html_safe_noop_under_limit() -> None:
    html = "<b>коротко</b>"
    assert split_html_safe(html, 1000) == html


def test_split_html_safe_closes_open_tag() -> None:
    html = "<b>очень длинный текст который не влезет целиком</b>"
    result = split_html_safe(html, 10)
    assert result.startswith("<b>")
    assert result.endswith("</b>")
    assert result.count("<b>") == 1
    assert result.count("</b>") == 1


def test_split_html_safe_does_not_cut_entity_in_half() -> None:
    html = "текст &amp; ещё текст"
    for limit in range(1, len(html) + 1):
        result = split_html_safe(html, limit)
        assert not re.search(r"&[a-zA-Z#][a-zA-Z0-9#]*$", result), (limit, result)
