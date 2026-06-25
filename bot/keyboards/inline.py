from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import settings
from bot.prompts.system_prompts import TEMPLATE_KEYS, TEMPLATES, TOP_LEVEL_KEYS

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
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🎙 Просто расшифровка", callback_data=f"m:{token}:plain")],
    ]
    for key in TOP_LEVEL_KEYS:
        rows.append([InlineKeyboardButton(text=TEMPLATES[key].label, callback_data=f"m:{token}:{key}")])
    rows.append([InlineKeyboardButton(text="📋 Шаблоны →", callback_data=f"m:{token}:tpl")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def templates_kb(token: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for key in TEMPLATE_KEYS:
        rows.append([InlineKeyboardButton(text=TEMPLATES[key].label, callback_data=f"t:{token}:{key}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"m:{token}:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plain_result_kb(token: str) -> InlineKeyboardMarkup:
    """Кнопки для режима 'Просто расшифровка': скачать транскрипт + получить текстом + назад."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 TXT", callback_data=f"dl:{token}:txt"),
                InlineKeyboardButton(text="📕 PDF", callback_data=f"dl:{token}:pdf"),
                InlineKeyboardButton(text="📘 DOCX", callback_data=f"dl:{token}:docx"),
            ],
            [InlineKeyboardButton(text="📩 Получить текстом", callback_data=f"msg:{token}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"m:{token}:back")],
        ]
    )


def ai_result_kb(token: str) -> InlineKeyboardMarkup:
    """Кнопки после AI-обработки (Самари, Роадмап и др.): скачать результат + назад."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 TXT", callback_data=f"dr:{token}:txt"),
                InlineKeyboardButton(text="📕 PDF", callback_data=f"dr:{token}:pdf"),
                InlineKeyboardButton(text="📘 DOCX", callback_data=f"dr:{token}:docx"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"m:{token}:back")],
        ]
    )


# Оставляем для обратной совместимости (старые кнопки в истории чата)
def result_kb(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 TXT", callback_data=f"dl:{token}:txt"),
                InlineKeyboardButton(text="📕 PDF", callback_data=f"dl:{token}:pdf"),
                InlineKeyboardButton(text="📘 DOCX", callback_data=f"dl:{token}:docx"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"m:{token}:back")],
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
            [
                InlineKeyboardButton(text="1 ч — 75 ₽", callback_data="buy:1"),
                InlineKeyboardButton(text="5 ч — 365 ₽", callback_data="buy:5"),
            ],
            [
                InlineKeyboardButton(text="10 ч — 699 ₽", callback_data="buy:10"),
                InlineKeyboardButton(text="30 ч — 1 799 ₽", callback_data="buy:30"),
            ],
            [InlineKeyboardButton(text="🔥 50 ч — 2 499 ₽  (50 ₽/ч)", callback_data="buy:50")],
            [InlineKeyboardButton(text="🎙 Расшифровать запись", callback_data="go:transcribe")],
        ]
    )


def paywall_kb() -> InlineKeyboardMarkup:
    """Кнопки при исчерпании лимита."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Купить тариф", callback_data="buy:tariffs")],
            [
                InlineKeyboardButton(text="🏠 Главная", url=settings.site_url),
                InlineKeyboardButton(text="🎙 Расшифровать", callback_data="go:transcribe"),
            ],
        ]
    )


def device_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 molvi-ai.ru", url=settings.site_url)],
        ]
    )
