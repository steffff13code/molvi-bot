from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import settings
from bot.prompts.system_prompts import TEMPLATE_KEYS, TEMPLATES

SITE_URL = settings.site_url
_BASE = settings.site_url.rstrip("/")


def _legal(path: str) -> str:
    return f"{_BASE}/legal/{path}/"


# ───────────────────────── Согласие ─────────────────────────

def consent_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📄 Пользовательское соглашение", url=_legal("terms"))],
            [InlineKeyboardButton(text="🔒 Политика конфиденциальности", url=_legal("privacy"))],
            [InlineKeyboardButton(text="✍️ Согласие на обработку данных", url=_legal("consent"))],
            [InlineKeyboardButton(text="📑 Публичная оферта", url=_legal("offer"))],
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="consent:accept")],
        ]
    )


# ───────────────────────── Выбор режима / шаблонов ─────────────────────────

def choose_mode_kb(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎙 Просто расшифровка", callback_data=f"m:{token}:plain")],
            [InlineKeyboardButton(text="📋 Шаблоны", callback_data=f"m:{token}:tpl")],
        ]
    )


def templates_kb(token: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for key in TEMPLATE_KEYS:
        rows.append([InlineKeyboardButton(text=TEMPLATES[key].label, callback_data=f"t:{token}:{key}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"m:{token}:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def result_kb(token: str) -> InlineKeyboardMarkup:
    """Кнопки под готовым результатом: скачать + сменить шаблон."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 TXT", callback_data=f"dl:{token}:txt"),
                InlineKeyboardButton(text="📕 PDF", callback_data=f"dl:{token}:pdf"),
                InlineKeyboardButton(text="📘 DOCX", callback_data=f"dl:{token}:docx"),
            ],
            [InlineKeyboardButton(text="🔁 Сменить шаблон", callback_data=f"chg:{token}")],
        ]
    )


# ───────────────────────── Тарифы / устройство / сайт ─────────────────────────

def website_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Наш сайт — molvi-ai.ru", url=SITE_URL)],
        ]
    )


def tariffs_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Тарифы на сайте", url=settings.landing_url)],
            [InlineKeyboardButton(text="🎙 Расшифровать запись", callback_data="go:transcribe")],
        ]
    )


def device_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Открыть molvi-ai.ru", url=settings.site_url)],
        ]
    )
