from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command

from bot.db.queries import upsert_user
from bot.keyboards.inline import device_kb, tariffs_kb, website_kb
from bot.keyboards.reply import (
    BTN_DEVICE,
    BTN_TARIFFS,
    BTN_TRANSCRIBE,
    main_menu_kb,
)

router = Router()

WELCOME_TEXT = """Привет, {name}! 👋

Я <b>МОЛВИ</b> — расшифровка аудио в текст прямо в Telegram.

Пришлите <b>голосовое, аудио или видео</b>, и я:

🎙 <b>Расшифрую</b> речь в текст (SaluteSpeech, Сбер)
📋 <b>Сделаю саммари</b> — короткое содержание
✅ <b>Выделю задачи</b> — To-do с исполнителями
🗺 <b>Составлю план</b> и 🔑 ключевые тезисы (GigaChat)
📄 <b>Отдам файлом</b> — TXT, PDF или DOCX

⚡ <b>Час записи — 3 минуты</b> расшифровки. Первые 15 минут — бесплатно. Без регистрации и программ.

<i>Лимиты: до 40 МБ, до 60 минут. Серверы в России (152-ФЗ).</i>

🌐 Сайт: <a href="https://molvi-ai.ru/">molvi-ai.ru</a>

👇 Нажмите «🎙 Расшифровать» или просто пришлите файл прямо сейчас!"""

TRANSCRIBE_HINT = (
    "🎙 Жду запись для расшифровки.\n\n"
    "Можно прислать:\n"
    "• Голосовое сообщение\n"
    "• Аудиофайл (MP3, M4A, WAV, OGG, FLAC…)\n"
    "• Видео или видео-кружок\n"
    "• Документ с аудио/видео\n\n"
    "Просто отправьте файл следующим сообщением."
)

TARIFFS_TEXT = (
    "💳 <b>Тарифы МОЛВИ</b>\n\n"
    "🎁 <b>15 минут — бесплатно</b>, прямо сейчас и без карты.\n\n"
    "Дальше — поминутно, с прогрессивной скидкой:\n"
    "• стартовая цена ~<b>3 ₽/мин</b>\n"
    "• чем больше пакет — тем дешевле минута\n\n"
    "⚡ Час записи расшифруется за <b>3 минуты</b> — вместо 6 часов вручную.\n"
    "💡 Стоимость часа записи — около <b>180 ₽</b>.\n\n"
    "Подробные пакеты — на сайте. А расшифровать запись можно прямо здесь 👇"
)

DEVICE_TEXT = (
    "🛒 <b>AI-диктофон МОЛВИ</b>\n\n"
    "Физическое устройство: записывает встречи, а расшифровка "
    "автоматически приходит в этого бота.\n\n"
    "Подробности, характеристики и заказ — на сайте 👇"
)

@router.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    user = message.from_user
    name = user.first_name if user and user.first_name else "друг"

    if user:
        await upsert_user(user_id=user.id, username=user.username, first_name=user.first_name)

    await message.answer(
        WELCOME_TEXT.format(name=name),
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(Command("new"))
@router.message(F.text == BTN_TRANSCRIBE)
# Совместимость со старой подписью кнопки.
@router.message(F.text == "🎙 Новая запись")
async def new_record_cmd(message: types.Message) -> None:
    await message.answer(TRANSCRIBE_HINT, reply_markup=main_menu_kb())


@router.callback_query(F.data == "go:transcribe")
async def go_transcribe(cb: types.CallbackQuery) -> None:
    if cb.message:
        await cb.message.answer(TRANSCRIBE_HINT, reply_markup=main_menu_kb())
    await cb.answer()


@router.message(F.text == BTN_TARIFFS)
async def tariffs(message: types.Message) -> None:
    await message.answer(
        TARIFFS_TEXT,
        reply_markup=tariffs_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(F.text == BTN_DEVICE)
async def buy_device(message: types.Message) -> None:
    await message.answer(
        DEVICE_TEXT,
        reply_markup=device_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(Command("records"))
async def records_cmd(message: types.Message) -> None:
    from bot.handlers.records import _send_records_page

    await _send_records_page(message, offset=0)


@router.message(Command("about"))
@router.message(F.text == "⚙️ О боте")
async def about_bot(message: types.Message) -> None:
    text = (
        "<b>МОЛВИ — расшифровка аудио в текст</b>\n\n"
        "Превращаю голос, аудио и видео в структурированный текст.\n\n"
        "<b>Технологии:</b>\n"
        "• Распознавание: SaluteSpeech (Сбер)\n"
        "• AI-обработка: GigaChat (Сбер)\n"
        "• Данные не покидают РФ (152-ФЗ)\n\n"
        "<b>Что умею:</b>\n"
        "📄 Полный текст (TXT/PDF/DOCX)\n"
        "📋 Саммари · ✅ Задачи · 🗺 План · 🔑 Тезисы\n\n"
        "🌐 Сайт: <a href=\"https://molvi-ai.ru/\">molvi-ai.ru</a>\n\n"
        "Версия: MVP 1.0"
    )
    await message.answer(
        text,
        reply_markup=website_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
