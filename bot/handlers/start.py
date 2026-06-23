from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command

from bot.config import settings
from bot.db.queries import get_stats, has_consent, set_consent, upsert_user
from bot.keyboards.inline import consent_kb, device_kb, tariffs_kb, website_kb
from bot.keyboards.reply import (
    BTN_DEVICE,
    BTN_TARIFFS,
    BTN_TEMPLATES,
    BTN_TRANSCRIBE,
    main_menu_kb,
)
from bot.prompts.system_prompts import TEMPLATE_KEYS, TEMPLATES
from bot.services.pricing import FREE_MINUTES, tariffs_text

router = Router()

WELCOME_TEXT = """Привет, {name}! 👋

Я <b>МОЛВИ</b> — расшифровка аудио в текст прямо в Telegram.

Пришлите <b>голосовое, аудио или видео</b>, и я:

🎙 <b>Расшифрую</b> речь в текст
📋 <b>Сделаю саммари</b> — на выбор 8 готовых шаблонов (протокол встречи, конспект лекции, интервью и др.)
📄 <b>Отдам файлом</b> — TXT, PDF или DOCX

⚡ Час записи — ~3 минуты расшифровки. Первые {free} минут — <b>бесплатно</b>.

🔒 Мы не храним ваши файлы и расшифровки — они остаются только у вас.

🌐 Сайт: <a href="https://molvi-ai.ru/">molvi-ai.ru</a>

👇 Нажмите «🎙 Расшифровать» или просто пришлите файл прямо сейчас!"""

CONSENT_TEXT = (
    "👋 Это МОЛВИ — расшифрую аудио в текст.\n\n"
    "Перед началом подтвердите, что принимаете:\n"
    "• Пользовательское соглашение\n"
    "• Политику конфиденциальности\n"
    "• Согласие на обработку данных\n"
    "• Публичную оферту\n\n"
    "Документы — по кнопкам ниже. Нажмите «✅ Подтвердить», чтобы продолжить."
)

TRANSCRIBE_HINT = (
    "🎙 Жду запись для расшифровки.\n\n"
    "Можно прислать:\n"
    "• Голосовое сообщение\n"
    "• Аудиофайл (MP3, M4A, WAV, OGG, FLAC…)\n"
    "• Видео или видео-кружок\n\n"
    "После распознавания выберите «🎙 Просто расшифровка» или «📋 Шаблоны»."
)

DEVICE_TEXT = (
    "🛒 <b>AI-диктофон МОЛВИ</b>\n\n"
    "Физическое устройство: записывает встречи, а расшифровка "
    "автоматически приходит в этого бота.\n\n"
    "Подробности, характеристики и заказ — на сайте 👇"
)


def _welcome(name: str) -> str:
    return WELCOME_TEXT.format(name=name, free=FREE_MINUTES)


@router.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    user = message.from_user
    name = user.first_name if user and user.first_name else "друг"

    if user:
        await upsert_user(user_id=user.id, username=user.username, first_name=user.first_name)

    if user and not await has_consent(user.id):
        await message.answer(CONSENT_TEXT, reply_markup=consent_kb(), disable_web_page_preview=True)
        return

    await message.answer(
        _welcome(name),
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "consent:accept")
async def on_consent(cb: types.CallbackQuery) -> None:
    user = cb.from_user
    if not user or not cb.message:
        return
    await set_consent(user.id)
    await cb.answer("Спасибо! Согласие сохранено.")
    name = user.first_name or "друг"
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.message.answer(
        _welcome(name),
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(Command("new"))
@router.message(F.text == BTN_TRANSCRIBE)
async def new_record_cmd(message: types.Message) -> None:
    await message.answer(TRANSCRIBE_HINT, reply_markup=main_menu_kb())


@router.callback_query(F.data == "go:transcribe")
async def go_transcribe(cb: types.CallbackQuery) -> None:
    if cb.message:
        await cb.message.answer(TRANSCRIBE_HINT, reply_markup=main_menu_kb())
    await cb.answer()


@router.message(F.text == BTN_TEMPLATES)
async def templates_info(message: types.Message) -> None:
    lines = "\n".join(f"• {TEMPLATES[k].label}" for k in TEMPLATE_KEYS)
    await message.answer(
        "📋 <b>Шаблоны саммари</b>\n\n"
        "Шаблон применяется к вашей записи. Доступны:\n"
        f"{lines}\n\n"
        "Пришлите аудио/видео — после распознавания выберите «📋 Шаблоны».",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )


@router.message(F.text == BTN_TARIFFS)
async def tariffs(message: types.Message) -> None:
    await message.answer(
        tariffs_text(),
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


@router.message(Command("stats2sstef"))
async def stats_cmd(message: types.Message) -> None:
    user = message.from_user
    if not user or not settings.admin_id or user.id != settings.admin_id:
        return  # доступно только владельцу
    s = await get_stats(30)
    tpl = "\n".join(f"   • {k}: {v}" for k, v in s["templates"].items()) or "   —"
    text = (
        "📊 <b>Статистика (30 дней)</b>\n\n"
        f"👥 Пользователей всего: {s['users_total']} (новых: {s['users_new']})\n"
        f"📈 DAU/WAU/MAU: {s['dau']} / {s['wau']} / {s['mau']}\n"
        f"🎧 Файлов: {s['files']} · минут: {s['minutes']} · ср.длина: {s['avg_minutes']} мин\n"
        f"🚧 Пэйвол: {s['paywall_hits']} · ⚠️ ошибок: {s['errors']}\n"
        f"⭐ В whitelist: {s['whitelist_count']}\n\n"
        f"<b>Шаблоны:</b>\n{tpl}"
    )
    await message.answer(text, parse_mode="HTML")
