from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command

from bot.keyboards.reply import BTN_HELP, main_menu_kb

router = Router()

HELP_TEXT = (
    "ℹ️ <b>Как пользоваться МОЛВИ</b>\n\n"
    "<b>1.</b> Пришлите голосовое, аудио или видео.\n"
    "<b>2.</b> Дождитесь расшифровки (обычно пара минут).\n"
    "<b>3.</b> Выберите, что сделать: полный текст (файлом TXT/PDF/DOCX), "
    "саммари, задачи, план или тезисы.\n\n"
    "<b>Кнопки меню:</b>\n"
    "🎙 Расшифровать — прислать запись\n"
    "💳 Тарифы — цены и бесплатный лимит\n"
    "🛒 Купить диктофон — про устройство\n"
    "ℹ️ Помощь — эта справка\n\n"
    "Команда /records — ваши сохранённые записи.\n\n"
    "<b>Поддерживаемые форматы:</b> голосовые, MP3, M4A, WAV, OGG, FLAC, "
    "видео (MP4, MOV) и др.\n"
    "<b>Лимиты:</b> до 40 МБ, до 60 минут. Серверы в России (152-ФЗ).\n\n"
    "🌐 Сайт: <a href=\"https://molvi-ai.ru/\">molvi-ai.ru</a>"
)


@router.message(Command("help"))
@router.message(F.text == BTN_HELP)
async def cmd_help(message: types.Message) -> None:
    await message.answer(
        HELP_TEXT,
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
