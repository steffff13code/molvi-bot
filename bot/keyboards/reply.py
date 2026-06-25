from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Тексты кнопок главного меню (используются и в хендлерах для сопоставления).
BTN_HOME = "🏠 Главная"
BTN_TRANSCRIBE = "🎙 Расшифровать"
BTN_TEMPLATES = "📋 Шаблоны"
BTN_TARIFFS = "💳 Тарифы / Купить минуты"
BTN_HELP = "ℹ️ Помощь"
BTN_MY_RECORDS = "📁 Мои записи"
BTN_DEVICE = BTN_HOME  # обратная совместимость


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_HOME)],
            [KeyboardButton(text=BTN_TRANSCRIBE)],
            [KeyboardButton(text=BTN_TEMPLATES), KeyboardButton(text=BTN_TARIFFS)],
            [KeyboardButton(text=BTN_HELP), KeyboardButton(text=BTN_MY_RECORDS)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Пришлите аудио, голосовое или видео…",
    )
