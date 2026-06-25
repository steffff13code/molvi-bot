from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command

from bot.keyboards.reply import BTN_HELP, main_menu_kb
from bot.services.pricing import FREE_MINUTES, PRICE_PER_HOUR

router = Router()


def _help_text() -> str:
    return (
        "ℹ️ <b>Как пользоваться МОЛВИ</b>\n\n"
        "<b>1.</b> Пришлите голосовое, аудио или видео.\n"
        "<b>2.</b> Дождитесь расшифровки — час записи ≈ 5 минут.\n"
        "<b>3.</b> Выберите «🎙 Просто расшифровка» или «📋 Шаблоны» "
        "(протокол встречи, конспект лекции, интервью и др.).\n"
        "<b>4.</b> Скачайте результат файлом TXT/PDF/DOCX. Можно «🔁 Сменить шаблон».\n\n"
        "<b>Кнопки меню:</b>\n"
        "🏠 Главная — перезапустить бот\n"
        "🎙 Расшифровать — прислать запись\n"
        "📋 Шаблоны — список форматов саммари\n"
        "💳 Тарифы / Купить минуты — цены и остаток\n"
        "📁 Мои записи — история расшифровок\n"
        "ℹ️ Помощь — эта справка\n\n"
        f"<b>Лимит:</b> {FREE_MINUTES} минут бесплатно, далее от {PRICE_PER_HOUR} ₽/час (пакеты до 2 499 ₽/50 ч).\n"
        "<b>Форматы:</b> голосовые, MP3, M4A, WAV, OGG, FLAC, видео (MP4, MOV) и др.\n"
        "<b>Приватность:</b> аудиофайл удаляется сразу после расшифровки. Серверы в России (152-ФЗ).\n\n"
        "🌐 Сайт: <a href=\"https://molvi-ai.ru/transcribe/\">molvi-ai.ru/transcribe</a>"
    )


@router.message(Command("help"))
@router.message(F.text == BTN_HELP)
async def cmd_help(message: types.Message) -> None:
    await message.answer(
        _help_text(),
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
