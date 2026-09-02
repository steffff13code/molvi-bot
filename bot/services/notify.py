"""Уведомления владельцу в Telegram: 402 от провайдера, необработанное исключение
в хендлере и т.п. — без этого владелец узнаёт об аварии от пользователя, а не от бота
(grep -rn "send_message" bot/ до этого PR давал ноль совпадений).

notify() — синхронный put_nowait в очередь: горячий путь (хендлер) не ждёт отправки
сообщения в Telegram и не падает, если Telegram недоступен. Один фоновый потребитель
разбирает очередь и шлёт с пейсингом, уважая для каждого типа события (kind) окно
агрегации, кулдаун и часовой потолок — иначе повторяющаяся ошибка устраивает шторм.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from loguru import logger


@dataclass
class Rule:
    immediate: bool          # слать сразу (True) или копить окном window_sec (False)
    window_sec: int          # длина окна агрегации (для immediate=False)
    cooldown_sec: int        # не повторять то же kind чаще, чем раз в столько секунд
    max_per_hour: int        # жёсткий потолок отправок этого kind в скользящий час


# 402 от Nexara/GigaChat — provider_quota; агрегируем окном 5 минут — error;
# token_low/queue_long/payment объявлены на будущее (PR-14 и др.), в этом PR не
# используются — сам факт наличия правила безопасен, RULES.get() с фолбэком ниже.
RULES: dict[str, Rule] = {
    "boot":           Rule(True,  0,   0,    10),
    "provider_quota": Rule(True,  0,   900,  4),
    "error":          Rule(False, 300, 0,    12),
    "token_low":      Rule(True,  0,   21600, 4),
    "queue_long":     Rule(True,  0,   1800, 4),
    "payment":        Rule(True,  0,   0,    60),
}
_DEFAULT_RULE = Rule(True, 0, 60, 30)

# Telegram: ~1 сообщение/сек в личку, ~20/мин в группу. Худший случай при всех
# потолках сразу — ≈130 сообщений в час = одно в 28с, внутри лимитов с запасом.
_DM_PACING_SEC = 1.1
_GROUP_PACING_SEC = 3.2


@dataclass
class _Event:
    kind: str
    text: str
    at: float = field(default_factory=time.monotonic)


class AdminNotifier:
    def __init__(self, *, dm_pacing_sec: float = _DM_PACING_SEC, group_pacing_sec: float = _GROUP_PACING_SEC) -> None:
        self._bot: Bot | None = None
        self._chat_id: int = 0
        self._is_group = False
        self._dm_pacing = dm_pacing_sec
        self._group_pacing = group_pacing_sec
        self._queue: asyncio.Queue[_Event] = asyncio.Queue(maxsize=500)
        self._consumer_task: asyncio.Task | None = None

        self._last_sent_at: dict[str, float] = {}
        self._sent_history: dict[str, list[float]] = {}
        self._window: dict[str, list[_Event]] = {}
        self._window_tasks: dict[str, asyncio.Task] = {}

    @property
    def is_group(self) -> bool:
        """Уведомления идут в группу — вызывающий код не должен класть в текст
        username/first_name (только user_id), см. заметку про ПДн в PR-9."""
        return self._is_group

    def bind(self, bot: Bot, chat_id: int, *, is_group: bool = False) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._is_group = is_group

    def start(self) -> None:
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(self._consume())

    def notify(self, kind: str, text: str) -> None:
        if not self._chat_id:
            return
        try:
            self._queue.put_nowait(_Event(kind=kind, text=text))
        except asyncio.QueueFull:
            logger.warning("AdminNotifier: очередь полна — событие '{kind}' отброшено", kind=kind)

    async def _consume(self) -> None:
        while True:
            event = await self._queue.get()
            rule = RULES.get(event.kind, _DEFAULT_RULE)
            if rule.immediate:
                await self._maybe_send(event, rule)
            else:
                self._add_to_window(event, rule)

    def _add_to_window(self, event: _Event, rule: Rule) -> None:
        bucket = self._window.setdefault(event.kind, [])
        bucket.append(event)
        running = self._window_tasks.get(event.kind)
        if running is None or running.done():
            self._window_tasks[event.kind] = asyncio.create_task(
                self._flush_window_later(event.kind, rule)
            )

    async def _flush_window_later(self, kind: str, rule: Rule) -> None:
        await asyncio.sleep(rule.window_sec)
        bucket = self._window.pop(kind, [])
        if not bucket:
            return
        if len(bucket) == 1:
            text = bucket[0].text
        else:
            shown = bucket[:10]
            text = f"⚠️ {len(bucket)} событий «{kind}» за {rule.window_sec}с:\n" + "\n".join(
                f"• {e.text}" for e in shown
            )
            if len(bucket) > len(shown):
                text += f"\n… и ещё {len(bucket) - len(shown)}"
        await self._maybe_send(_Event(kind=kind, text=text), rule)

    def _within_cooldown(self, kind: str, rule: Rule) -> bool:
        last = self._last_sent_at.get(kind)
        return bool(rule.cooldown_sec and last is not None and time.monotonic() - last < rule.cooldown_sec)

    def _over_hourly_cap(self, kind: str, rule: Rule) -> bool:
        now = time.monotonic()
        recent = [t for t in self._sent_history.get(kind, []) if now - t < 3600]
        self._sent_history[kind] = recent
        return len(recent) >= rule.max_per_hour

    async def _maybe_send(self, event: _Event, rule: Rule) -> None:
        if self._within_cooldown(event.kind, rule) or self._over_hourly_cap(event.kind, rule):
            return
        sent = await self._send(event.text)
        if not sent:
            return
        now = time.monotonic()
        self._last_sent_at[event.kind] = now
        self._sent_history.setdefault(event.kind, []).append(now)

    async def _send(self, text: str) -> bool:
        if not self._bot or not self._chat_id:
            return False
        pacing = self._group_pacing if self._is_group else self._dm_pacing
        for _ in range(3):
            try:
                await self._bot.send_message(self._chat_id, text)
                await asyncio.sleep(pacing)
                return True
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception as e:
                logger.warning("AdminNotifier: не удалось отправить сообщение: {e}", e=e)
                return False
        return False


notifier = AdminNotifier()
