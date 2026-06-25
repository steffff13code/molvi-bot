"""Единый источник правды по ценам и лимитам."""

from __future__ import annotations

from bot.config import settings

FREE_MINUTES: int = settings.free_minutes
PRICE_PER_HOUR: int = 50  # минимальная цена за час (пакет 50 ч)

# Пакеты: (часов, цена ₽, ₽/час или None)
_PACKAGES = [
    (1,  75,   None),
    (5,  365,  73),
    (10, 699,  70),
    (30, 1799, 60),
    (50, 2499, 50),
]


def _fmt_minutes(minutes: float) -> str:
    """60 мин → '1 ч', 90 мин → '1 ч 30 мин', 45 мин → '45 мин'."""
    m = int(round(minutes))
    if m < 60:
        return f"{m} мин"
    h, rem = divmod(m, 60)
    return f"{h} ч {rem} мин" if rem else f"{h} ч"


def profile_block(
    used_minutes: float,
    gifted_minutes: float,
    whitelisted: bool,
) -> str:
    """Блок «Ваш профиль» для сообщения тарифов."""
    from bot.config import settings as s
    free = s.free_minutes

    remaining = max(0.0, free - used_minutes)
    actual_used = max(0.0, used_minutes)       # реально потрачено пользователем

    if whitelisted:
        return (
            "👤 <b>Ваш профиль</b>\n"
            "⭐ Статус: <b>Безлимит</b> — лимиты не применяются"
        )

    if gifted_minutes > 0:
        pkg = f"🎁 Подарочный пакет (+{_fmt_minutes(gifted_minutes)})"
    else:
        pkg = f"🎁 Бесплатный пакет ({_fmt_minutes(free)})"

    lines = [
        "👤 <b>Ваш профиль</b>",
        f"📦 Пакет: {pkg}",
        f"📊 Использовано: <b>{_fmt_minutes(actual_used)}</b>",
        f"⏳ Осталось: <b>{_fmt_minutes(remaining)}</b>",
    ]
    if remaining == 0:
        lines.append("🚫 <i>Лимит исчерпан — купите пакет ниже</i>")
    return "\n".join(lines)


def tariffs_text(
    used_minutes: float = 0.0,
    gifted_minutes: float = 0.0,
    whitelisted: bool = False,
) -> str:
    lines = [
        "💳 <b>Тарифы МОЛВИ</b>\n",
        profile_block(used_minutes, gifted_minutes, whitelisted),
        "",
        "<b>Платные пакеты:</b>",
    ]
    for hours, price, per_h in _PACKAGES:
        note = f"  <i>({per_h} ₽/ч)</i>" if per_h else ""
        lines.append(f"• {hours} ч — <b>{price} ₽</b>{note}")
    lines += [
        "",
        "⚡ Час записи расшифровывается за ~5 минут.",
        "\nЧтобы купить пакет — выберите ниже или напишите нам.",
    ]
    return "\n".join(lines)


def paywall_text() -> str:
    return (
        f"🚧 <b>Бесплатный лимит исчерпан</b>\n\n"
        f"Вы использовали бесплатные {FREE_MINUTES} минут расшифровки.\n\n"
        "Чтобы продолжить — купите пакет минут:\n"
        "• 1 ч — <b>75 ₽</b>\n"
        "• 5 ч — <b>365 ₽</b>  (73 ₽/ч)\n"
        "• 10 ч — <b>699 ₽</b>  (70 ₽/ч)\n"
        "• 30 ч — <b>1 799 ₽</b>  (60 ₽/ч)\n"
        "• 50 ч — <b>2 499 ₽</b>  (50 ₽/ч) 🔥\n\n"
        "Напишите нам, чтобы пополнить пакет — мы поможем."
    )
