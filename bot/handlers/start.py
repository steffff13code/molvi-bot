from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command

from bot.config import settings
from bot.db.queries import get_minutes_used, get_stats, get_stats_full, get_user_info, gift_minutes, has_consent, is_whitelisted, set_consent, upsert_user, whitelist_add, whitelist_remove
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
from bot.services.nav_cleanup import nav_cleanup
from bot.services.pricing import FREE_MINUTES, tariffs_text

router = Router()

# Отслеживаем последнее «главное» сообщение каждого пользователя —
# при повторном нажатии «Главная» редактируем его вместо отправки нового.
_last_home: dict[int, int] = {}  # user_id → message_id

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
    user = message.from_user
    sent = await message.answer(TRANSCRIBE_HINT, reply_markup=main_menu_kb())
    if user:
        nav_cleanup.track(user.id, sent.message_id)


@router.callback_query(F.data == "go:transcribe")
async def go_transcribe(cb: types.CallbackQuery) -> None:
    if cb.message:
        await cb.message.answer(TRANSCRIBE_HINT, reply_markup=main_menu_kb())
    await cb.answer()


@router.message(F.text == BTN_TEMPLATES)
async def templates_info(message: types.Message) -> None:
    user = message.from_user
    lines = "\n".join(f"• {TEMPLATES[k].label}" for k in TEMPLATE_KEYS)
    sent = await message.answer(
        "📋 <b>Шаблоны саммари</b>\n\n"
        "Шаблон применяется к вашей записи. Доступны:\n"
        f"{lines}\n\n"
        "Пришлите аудио/видео — после распознавания выберите «📋 Шаблоны».",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )
    if user:
        nav_cleanup.track(user.id, sent.message_id)


@router.message(F.text == BTN_TARIFFS)
async def tariffs(message: types.Message) -> None:
    user = message.from_user
    used = 0.0
    gifted = 0.0
    wl = False
    if user:
        wl = await is_whitelisted(user.id, user.username)
        info = await get_user_info(user.id)
        if info:
            used = float(info.get("minutes_used") or 0)
            gifted = float(info.get("gifted_minutes") or 0)
    sent = await message.answer(
        tariffs_text(used_minutes=used, gifted_minutes=gifted, whitelisted=wl),
        reply_markup=tariffs_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    if user:
        nav_cleanup.track(user.id, sent.message_id)


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
    text = _welcome(name)

    # Удаляем предыдущее «Главная» сообщение и отправляем новое
    if user:
        prev_id = _last_home.pop(user.id, None)
        if prev_id:
            try:
                await message.bot.delete_message(message.chat.id, prev_id)
            except Exception:
                pass

    sent = await message.answer(
        text,
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    if user:
        _last_home[user.id] = sent.message_id


_TEMPLATE_NAMES = {
    "plain":      "Просто расшифровка",
    "summary":    "Самари",
    "roadmap":    "Роадмап (план действий)",
    "keypoints":  "Ключевые моменты",
    "tasks":      "Список задач",
    "protocol":   "Протокол встречи",
    "call":       "Звонок / переговоры",
    "lecture":    "Конспект лекции",
    "legal":      "Юр. консультация",
    "hr":         "Собеседование HR",
    "interview":  "Интервью",
    "note":       "Личная заметка",
    "therapy":    "Сессия с психологом",
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
        f"• Активны сегодня / за 7 дн / за 30 дн: <b>{s['dau']} / {s['wau']} / {s['mau']}</b>",
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
        f"• Уперлись в бесплатный лимит: <b>{s['paywall_hits']}</b> событий",
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


# ──────────────────── Команды управления пользователями (только admin) ────────


def _admin_only(user: types.User | None) -> bool:
    return bool(user and settings.admin_id and user.id == settings.admin_id)


@router.message(Command("givehours"))
async def cmd_give_hours(message: types.Message) -> None:
    """Подарить пользователю N часов. Использование: /givehours <tg_id> <часов>"""
    if not _admin_only(message.from_user):
        return
    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Использование: /givehours <tg_id> <часов>\nПример: /givehours 1977145797 10")
        return
    tg_id = int(parts[1])
    hours = int(parts[2])
    minutes = hours * 60.0
    ok = await gift_minutes(tg_id, minutes)
    if ok:
        remaining = max(0.0, await get_minutes_used(tg_id))
        effective_free = settings.free_minutes + minutes  # сколько всего получит
        await message.answer(
            f"✅ Пользователю <code>{tg_id}</code> подарено <b>{hours} ч ({int(minutes)} мин)</b>.\n"
            f"Теперь у него доступно ещё ~<b>{int(max(0, -remaining + minutes))} мин</b> "
            f"до следующего пэйвола.",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"⚠️ Пользователь <code>{tg_id}</code> не найден в базе.\n"
            "Он должен хотя бы раз запустить бота.",
            parse_mode="HTML",
        )


@router.message(Command("wladd"))
async def cmd_wl_add(message: types.Message) -> None:
    """Добавить в whitelist (безлимит). Использование: /wladd <tg_id> [username] [заметка]"""
    if not _admin_only(message.from_user):
        return
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 2:
        await message.answer("Использование: /wladd <tg_id> [username] [заметка]\nПример: /wladd 1977145797 MrNikola1 подарок")
        return
    tg_id = int(parts[1]) if parts[1].isdigit() else None
    username = parts[2].lstrip("@") if len(parts) > 2 else None
    note = parts[3] if len(parts) > 3 else None
    if tg_id is None:
        await message.answer("⚠️ tg_id должен быть числом.")
        return
    ok = await whitelist_add(tg_id=tg_id, username=username, note=note)
    if ok:
        un = f" (@{username})" if username else ""
        await message.answer(f"✅ <code>{tg_id}</code>{un} добавлен в whitelist — безлимит включён.", parse_mode="HTML")
    else:
        await message.answer(f"⚠️ Не удалось добавить (возможно, уже есть в whitelist).")


@router.message(Command("wlrm"))
async def cmd_wl_remove(message: types.Message) -> None:
    """Удалить из whitelist по ID записи. Использование: /wlrm <id_записи>"""
    if not _admin_only(message.from_user):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /wlrm <id_записи>\nID записи — из /wllist")
        return
    ok = await whitelist_remove(int(parts[1]))
    if ok:
        await message.answer(f"✅ Запись #{parts[1]} удалена из whitelist.")
    else:
        await message.answer(f"⚠️ Запись #{parts[1]} не найдена.")


@router.message(Command("userinfo"))
async def cmd_user_info(message: types.Message) -> None:
    """Проверить пакет и статус пользователя. Использование: /userinfo <tg_id>"""
    if not _admin_only(message.from_user):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Использование: /userinfo <tg_id>\nПример: /userinfo 1977145797")
        return

    from bot.services.pricing import FREE_MINUTES, _fmt_minutes
    tg_id = int(parts[1])
    info = await get_user_info(tg_id)
    if not info:
        await message.answer(
            f"❌ Пользователь <code>{tg_id}</code> не найден в базе.\n"
            "Он должен хотя бы раз запустить бота.",
            parse_mode="HTML",
        )
        return

    used = float(info.get("minutes_used") or 0)
    gifted = float(info.get("gifted_minutes") or 0)
    remaining = max(0.0, FREE_MINUTES - used)
    wl = info.get("whitelist")
    name = info.get("first_name") or "—"
    uname = f"@{info['username']}" if info.get("username") else "нет"

    if wl:
        status = f"⭐ Безлимит (whitelist #{wl['id']})"
        if wl.get("note"):
            status += f" — {wl['note']}"
    elif gifted > 0:
        status = f"🎁 Подарочный пакет (+{_fmt_minutes(gifted)})"
    else:
        status = "🎁 Бесплатный пакет"

    lines = [
        f"👤 <b>Пользователь {tg_id}</b>",
        f"Имя: {name}  |  Username: {uname}",
        f"Зарегистрирован: {(info.get('created_at') or '')[:16]}",
        f"Последняя активность: {(info.get('last_seen_at') or '')[:16]}",
        "",
        f"📦 <b>Пакет:</b> {status}",
        f"📊 Подарено всего: <b>{_fmt_minutes(gifted)}</b>",
        f"📉 Использовано (minutes_used): <b>{used:.1f}</b>",
        f"⏳ Осталось: <b>{_fmt_minutes(remaining)}</b>",
        f"✅ Согласие: {'да' if info.get('consent_at') else 'нет'}",
    ]
    await message.answer("\n".join(lines), parse_mode="HTML")
