from __future__ import annotations

import re

from aiogram.types import BufferedInputFile


# Маркеры начала строк, которые НЕ являются заголовками (пункты списков).
_BULLET_PREFIXES = ("—", "–", "•", "-", "*", "☐", "□", "▪", ">", "&gt;")

# Метки-поля вида «Цель: …», «Тема: …» — выделяем жирным только саму метку.
_FIELD_LABEL_RE = re.compile(r"^([A-Za-zА-Яа-яЁё][^:<>\n]{1,40}):(\s+\S)")


def _style_line_headers(text: str) -> str:
    """Выделяет жирным строки-заголовки и метки-поля (для промптов без markdown).

    Заголовок — короткая строка без двоеточия и без маркера списка
    («О чём запись», «Ход разговора», «Главные мысли / тезисы»).
    Метка-поле — «Цель: текст» → «<b>Цель:</b> текст».
    """
    out: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or "<b>" in line:
            out.append(line)
            continue
        # Пункт списка / нумерованный — не трогаем
        if stripped[0].isdigit() or stripped.startswith(_BULLET_PREFIXES):
            out.append(line)
            continue
        # Метка-поле «Цель: …» → жирная метка
        m = _FIELD_LABEL_RE.match(stripped)
        if m:
            label = m.group(1)
            rest = stripped[len(label) + 1:]
            out.append(f"<b>{label}:</b>{rest}")
            continue
        # Короткая строка без двоеточия и без конечной пунктуации = заголовок секции.
        # Предложения-проза заканчиваются на . ! ? , ; — их не трогаем.
        if (
            ":" not in stripped
            and len(stripped) <= 60
            and stripped[-1] not in ".!?,;"
        ):
            out.append(f"<b>{stripped}</b>")
            continue
        out.append(line)
    return "\n".join(out)


def md_to_html(text: str) -> str:
    """Конвертирует Markdown GigaChat в HTML для Telegram (parse_mode=HTML).

    Экранирует HTML-спецсимволы, конвертирует **жирный**, ## заголовки,
    маркеры списков, а также выделяет жирным строки-заголовки v2-промптов.
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
    # Жирные заголовки секций и метки-поля
    text = _style_line_headers(text)
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


# Ключи /start-payload (PR-13): s=source, m=medium, c=campaign, k=ключевая фраза,
# i=Метрика ClientID, y=yclid — зона A4; p=токен платежа, r=реферальный код,
# g=промокод — зона A7 (понадобятся в PR-14).
_PAYLOAD_KEYS = frozenset("smckiyprg")
_PAYLOAD_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def parse_start_payload(raw: str | None) -> dict[str, str]:
    """'s_yd-m_cpc-c_brand' → {'s':'yd','m':'cpc','c':'brand'}.

    Payload приходит от пользователя: доверять нельзя. Любой мусор → {}.
    Незнакомые ключи молча отбрасываются. Значения обрезаются до 16 символов.
    """
    if not raw or not _PAYLOAD_RE.match(raw):
        return {}
    out: dict[str, str] = {}
    for part in raw.split("-"):
        key, sep, val = part.partition("_")
        if sep and key in _PAYLOAD_KEYS and val:
            out[key] = val[:16]
    if not out and raw:  # обратная совместимость: голый source (например, /start promo)
        out["s"] = raw[:16]
    return out


def source_label(p: dict[str, str]) -> str:
    return f"{p.get('s', 'direct')}/{p.get('m', 'none')}"


# Теги, которые реально встречаются в md_to_html() и которые Telegram parse_mode=HTML понимает.
_SAFE_HTML_TAGS = {"b", "i", "u", "s", "code", "pre", "a"}

# Тег целиком (<...>) или HTML-сущность (&...;) целиком, иначе — один любой символ.
# Атомарность тега/сущности — то, что не даёт split_html_safe разрезать их пополам.
_HTML_TOKEN_RE = re.compile(r"<[^>]*>|&[a-zA-Z#][a-zA-Z0-9#]*;|.", re.DOTALL)


def split_html_safe(html: str, limit: int) -> str:
    """Обрезает HTML до limit символов так, чтобы результат остался валидным
    для Telegram parse_mode=HTML: не рвёт теги и сущности, закрывает открытое.

    Итоговая строка может быть чуть длиннее limit — на длину дописанных
    закрывающих тегов; это ожидаемо, вызывающий код должен оставлять запас.
    """
    if len(html) <= limit:
        return html

    stack: list[str] = []
    out: list[str] = []
    length = 0

    for unit in _HTML_TOKEN_RE.finditer(html):
        token = unit.group(0)
        if length + len(token) > limit:
            break
        out.append(token)
        length += len(token)

        if token.startswith("<") and token.endswith(">") and len(token) > 1:
            inner = token[1:-1].strip()
            if inner.startswith("/"):
                name = inner[1:].strip().lower()
                if stack and stack[-1] == name:
                    stack.pop()
            else:
                name = inner.split()[0].lower() if inner.split() else ""
                if name in _SAFE_HTML_TAGS and not inner.endswith("/"):
                    stack.append(name)

    result = "".join(out)
    for name in reversed(stack):
        result += f"</{name}>"
    return result
