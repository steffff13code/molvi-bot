from __future__ import annotations

from aiogram.types import BufferedInputFile


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

