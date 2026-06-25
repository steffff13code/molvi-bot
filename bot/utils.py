from __future__ import annotations

import re

from aiogram.types import BufferedInputFile


def md_to_html(text: str) -> str:
    """Конвертирует Markdown GigaChat в HTML для Telegram (parse_mode=HTML).

    Экранирует HTML-спецсимволы, затем конвертирует **жирный**, *текст*,
    # Заголовки, маркеры списков в соответствующие HTML-теги/символы.
    """
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # **жирный** → <b>жирный</b>  (раньше, чтобы не задеть одиночные *)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    # ### Заголовок → <b>Заголовок</b>
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    # Маркеры списков (* item, - item) в начале строки → убираем символ
    text = re.sub(r"^[*\-]\s+", "• ", text, flags=re.MULTILINE)
    # Оставшиеся *одиночные* → убираем звёздочки
    text = re.sub(r"\*(.+?)\*", r"\1", text, flags=re.DOTALL)
    return text


def split_telegram_text(text: str, limit: int = 4096) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    chunk = []
    size = 0
    for line in text.splitlines(True):
        if size + len(line) > limit and chunk:
            parts.append("".join(chunk))
            chunk = [line]
            size = len(line)
        else:
            chunk.append(line)
            size += len(line)
    if chunk:
        parts.append("".join(chunk))
    # fallback (если одна строка слишком длинная)
    fixed: list[str] = []
    for p in parts:
        if len(p) <= limit:
            fixed.append(p)
        else:
            for i in range(0, len(p), limit):
                fixed.append(p[i : i + limit])
    return fixed


def as_txt_file(filename: str, text: str) -> BufferedInputFile:
    data = text.encode("utf-8")
    return BufferedInputFile(data, filename=filename)
