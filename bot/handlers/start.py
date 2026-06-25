from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command

from bot.config import settings
from bot.db.queries import get_minutes_used, get_stats, get_stats_full, has_consent, is_whitelisted, set_consent, upsert_user
from bot.keyboards.inline import consent_kb, device_kb, tariffs_kb, website_kb
from bot.keyboards.reply import (
    BTN_DEVICE,
    BTN_HOME,
    BTN_MY_RECORDS,
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

⚡ Час записи — ~5 минут расшифровки. Первые {free} минут — <b>бесплатно</b>.

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
    user = message.from_user
    used = 0.0
    wl = False
    if user:
        wl = await is_whitelisted(user.id, user.username)
        if not wl:
            used = await get_minutes_used(user.id)
    await message.answer(
        tariffs_text(used_minutes=used, whitelisted=wl),
        reply_markup=tariffs_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("buy:"))
async def buy_stub(cb: types.CallbackQuery) -> None:
    # Заглушка: реальная оплата пока не подключена.
    await cb.answer()
    if cb.message:
        await cb.message.answer(
            "💳 Онлайн-оплата скоро будет доступна.\n\n"
            "Чтобы купить минуты уже сейчас — напишите нам, и мы откроем доступ. "
            "А первые 60 минут доступны бесплатно прямо в боте.",
        )


@router.message(F.text == BTN_HOME)
async def home_handler(message: types.Message) -> None:
    user = message.from_user
    name = user.first_name if user and user.first_name else "друг"
    await message.answer(
        _welcome(name),
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


_TEMPLATE_NAMES = {
    "plain":     "Просто расшифровка",
    "protocol":  "Протокол встречи",
    "call":      "Звонок / переговоры",
    "lecture":   "Конспект лекции",
    "legal":     "Юр. консультация",
    "hr":        "Собеседование HR",
    "interview": "Интервью",
    "note":      "Личная заметка",
    "therapy":   "Сессия с психологом",
}

_PERIOD_LABELS = {
    1: "1 день",
    3: "3 дня",
    5: "5 дней",
    7: "7 дней",
    30: "30 дней",
    0: "Всё время",
}


def _pct(num: int, denom: int) -> str:
    if denom == 0:
        return "—"
    return f"{round(num / denom * 100)}%"


def _fmt_time_ago(iso: str | None) -> str:
    """Возвращает «N часов назад» / «N дней назад» для ISO-метки из SQLite."""
    if not iso:
        return "никогда"
    import datetime
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        delta = datetime.datetime.now(datetime.timezone.utc) - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return "только что"
        if secs < 3600:
            return f"{secs // 60} мин назад"
        if secs < 86400:
            h = secs // 3600
            return f"{h} {'час' if h == 1 else 'ч'} назад"
        d = secs // 86400
        return f"{d} {'день' if d == 1 else 'дн'} назад"
    except Exception:
        return iso[:16]


def _build_stats_text(s: dict) -> str:
    period_label = _PERIOD_LABELS.get(s["period_days"], f"{s['period_days']} дней")
    total = s["users_total"]
    new = s["users_new"]
    audio = s["users_audio"]
    audio_total = s["users_audio_total"]
    pw_users = s["users_paywall"]

    # Воронка: база — все пользователи за период (или всего)
    funnel_base = total if s["period_days"] == 0 else new if new > 0 else total

    lines = [
        f"📊 <b>Статистика МОЛВИ — {period_label}</b>",
        "<i>(ваш аккаунт исключён из всех счётчиков)</i>",
        "",
        "━━━━━━━ 👥 ПОЛЬЗОВАТЕЛИ ━━━━━━━",
        f"• Всего в базе: <b>{total}</b>",
        f"• Новых за период: <b>{new}</b>",
        f"• Отправляли аудио за период: <b>{audio}</b>",
        f"• Всего когда-либо отправляли: <b>{audio_total}</b>",
        f"• DAU / WAU / MAU: <b>{s['dau']} / {s['wau']} / {s['mau']}</b>",
        "",
        "━━━━━━━ 🎙 РАСШИФРОВКИ ━━━━━━━",
        f"• Файлов принято: <b>{s['files']}</b>",
        f"• Минут расшифровано: <b>{s['minutes']}</b>",
        f"• Средняя длина записи: <b>{s['avg_minutes']} мин</b>",
        f"• Самая длинная запись: <b>{s['max_minutes']} мин</b>",
        f"• Последняя расшифровка: <b>{_fmt_time_ago(s['last_recognize_at'])}</b>",
    ]

    # Шаблоны
    if s["templates"]:
        lines += ["", "━━━━━━━ 📋 ШАБЛОНЫ ━━━━━━━"]
        for key, cnt in s["templates"].items():
            name = _TEMPLATE_NAMES.get(key, key)
            lines.append(f"• {name}: <b>{cnt}</b>")

    # Экспорт
    if s["exports_total"] > 0:
        lines += ["", "━━━━━━━ 📁 ЭКСПОРТ ━━━━━━━"]
        parts = [f"{fmt.upper()}: {cnt}" for fmt, cnt in s["formats"].items()]
        lines.append(f"• {' · '.join(parts)}")
        lines.append(f"• Всего скачиваний: <b>{s['exports_total']}</b>")

    # Воронка конверсии
    lines += [
        "",
        "━━━━━━━ 📈 ВОРОНКА ━━━━━━━",
        f"• Запустили бот: <b>{total}</b>",
        f"• Отправили аудио: <b>{audio_total}</b> ({_pct(audio_total, total)} от всех)",
        f"• Использовали за период: <b>{audio}</b> ({_pct(audio, total)} от всех)",
        f"• Упёрлись в лимит: <b>{pw_users}</b> ({_pct(pw_users, audio if audio else total)})",
        "• Оплатили: <b>0</b> — эквайринг не подключён",
    ]

    # Пэйвол и ошибки
    lines += [
        "",
        "━━━━━━━ ⚙️ СИСТЕМА ━━━━━━━",
        f"• Пэйвол-срабатываний: <b>{s['paywall_hits']}</b>",
        f"• Ошибок распознавания: <b>{s['errors']}</b>",
        f"• В whitelist (безлимит): <b>{s['whitelist_count']}</b>",
    ]

    return "\n".join(lines)


def _stats_period_kb(current: int) -> types.InlineKeyboardMarkup:
    periods = [1, 3, 5, 7, 30, 0]
    labels = {1: "1д", 3: "3д", 5: "5д", 7: "7д", 30: "30д", 0: "Всё"}
    buttons = [
        types.InlineKeyboardButton(
            text=f"[{labels[p]}]" if p == current else labels[p],
            callback_data=f"stats_period:{p}",
        )
        for p in periods
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=[buttons])


@router.message(Command("stats2sstef"))
async def stats_cmd(message: types.Message) -> None:
    user = message.from_user
    if not user or not settings.admin_id or user.id != settings.admin_id:
        return
    s = await get_stats_full(days=7, exclude_admin=True)
    await message.answer(
        _build_stats_text(s),
        parse_mode="HTML",
        reply_markup=_stats_period_kb(7),
    )


@router.callback_query(F.data.startswith("stats_period:"))
async def stats_period_cb(callback: types.CallbackQuery) -> None:
    user = callback.from_user
    if not user or not settings.admin_id or user.id != settings.admin_id:
        await callback.answer("Нет доступа", show_alert=True)
        return
    days = int(callback.data.split(":")[1])
    s = await get_stats_full(days=days, exclude_admin=True)
    text = _build_stats_text(s)
    kb = _stats_period_kb(days)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass
    await callback.answer()
