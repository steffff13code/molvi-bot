from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import settings

SITE_URL = settings.site_url


def website_kb() -> InlineKeyboardMarkup:
    """Inline-кнопка со ссылкой на сайт."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Наш сайт — molvi-ai.ru", url=SITE_URL)],
        ]
    )


def tariffs_kb() -> InlineKeyboardMarkup:
    """Кнопки под сообщением о тарифах: подробнее на сайте + сразу расшифровать."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Тарифы на сайте", url=settings.landing_url)],
            [InlineKeyboardButton(text="🎙 Расшифровать запись", callback_data="go:transcribe")],
        ]
    )


def device_kb() -> InlineKeyboardMarkup:
    """Кнопка перехода на сайт устройства."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Открыть molvi-ai.ru", url=settings.site_url)],
        ]
    )


def record_actions_kb(record_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 Полный текст", callback_data=f"rec:{record_id}:fulltext"),
                InlineKeyboardButton(text="📋 Саммари", callback_data=f"rec:{record_id}:summary"),
            ],
            [
                InlineKeyboardButton(text="✅ Задачи (To-do)", callback_data=f"rec:{record_id}:todo"),
                InlineKeyboardButton(text="🗺 План / Roadmap", callback_data=f"rec:{record_id}:roadmap"),
            ],
            [
                InlineKeyboardButton(text="🔑 Ключевые тезисы", callback_data=f"rec:{record_id}:keywords"),
            ],
            [
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"rec:{record_id}:delete"),
                InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="reclist:0"),
            ],
        ]
    )


def download_format_kb(record_id: int) -> InlineKeyboardMarkup:
    """Выбор формата для скачивания полного текста."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 TXT", callback_data=f"dl:{record_id}:txt"),
                InlineKeyboardButton(text="📕 PDF", callback_data=f"dl:{record_id}:pdf"),
                InlineKeyboardButton(text="📘 DOCX", callback_data=f"dl:{record_id}:docx"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"recopen:{record_id}")],
        ]
    )


def records_pager_kb(offset: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    if has_prev:
        buttons.append(InlineKeyboardButton(text="⬅️ Раньше", callback_data=f"reclist:{max(0, offset - 10)}"))
    if has_next:
        buttons.append(InlineKeyboardButton(text="Позже ➡️", callback_data=f"reclist:{offset + 10}"))

    if buttons:
        return InlineKeyboardMarkup(inline_keyboard=[buttons])
    return InlineKeyboardMarkup(inline_keyboard=[])
