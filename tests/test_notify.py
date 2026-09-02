"""AdminNotifier (PR-9): пейсинг/кулдаун/потолок/окно агрегации — без этого
повторяющаяся ошибка устраивает шторм сообщений владельцу, и notify() не должен
блокировать вызывающий хендлер."""
from __future__ import annotations

import asyncio

import pytest
from aiogram.exceptions import TelegramRetryAfter

from bot.services.notify import AdminNotifier, RULES, Rule


class _FakeBot:
    def __init__(self, fail_times: int = 0, retry_after: float = 0.05) -> None:
        self.sent: list[str] = []
        self._fail_times = fail_times
        self._retry_after = retry_after

    async def send_message(self, chat_id: int, text: str) -> None:
        if self._fail_times > 0:
            self._fail_times -= 1
            raise TelegramRetryAfter(method=None, message="flood", retry_after=self._retry_after)
        self.sent.append(text)


@pytest.fixture
def custom_rule():
    """Регистрирует временное правило с быстрыми таймингами для теста, убирает после."""
    added: list[str] = []

    def _register(kind: str, rule: Rule) -> None:
        RULES[kind] = rule
        added.append(kind)

    yield _register
    for kind in added:
        RULES.pop(kind, None)


async def test_immediate_rule_sends_right_away(custom_rule) -> None:
    custom_rule("t_immediate", Rule(True, 0, 0, 10))
    bot = _FakeBot()
    n = AdminNotifier(dm_pacing_sec=0.01, group_pacing_sec=0.01)
    n.bind(bot, chat_id=123)
    n.start()

    n.notify("t_immediate", "hello")
    await asyncio.sleep(0.05)

    assert bot.sent == ["hello"]


async def test_cooldown_suppresses_repeat_then_allows_after_expiry(custom_rule) -> None:
    custom_rule("t_cooldown", Rule(True, 0, 0.2, 10))
    bot = _FakeBot()
    n = AdminNotifier(dm_pacing_sec=0.01, group_pacing_sec=0.01)
    n.bind(bot, chat_id=123)
    n.start()

    n.notify("t_cooldown", "first")
    await asyncio.sleep(0.05)
    n.notify("t_cooldown", "second")
    await asyncio.sleep(0.05)
    assert bot.sent == ["first"]  # второе подавлено кулдауном

    await asyncio.sleep(0.25)
    n.notify("t_cooldown", "third")
    await asyncio.sleep(0.05)
    assert bot.sent == ["first", "third"]


async def test_hourly_cap_blocks_after_limit(custom_rule) -> None:
    custom_rule("t_cap", Rule(True, 0, 0, 2))
    bot = _FakeBot()
    n = AdminNotifier(dm_pacing_sec=0.01, group_pacing_sec=0.01)
    n.bind(bot, chat_id=123)
    n.start()

    for i in range(5):
        n.notify("t_cap", f"msg{i}")
        await asyncio.sleep(0.02)

    assert len(bot.sent) == 2


async def test_window_rule_aggregates_multiple_events(custom_rule) -> None:
    custom_rule("t_window", Rule(False, 0.1, 0, 10))
    bot = _FakeBot()
    n = AdminNotifier(dm_pacing_sec=0.01, group_pacing_sec=0.01)
    n.bind(bot, chat_id=123)
    n.start()

    n.notify("t_window", "one")
    n.notify("t_window", "two")
    n.notify("t_window", "three")
    await asyncio.sleep(0.25)

    assert len(bot.sent) == 1
    assert "3 событий" in bot.sent[0]
    for part in ("one", "two", "three"):
        assert part in bot.sent[0]


async def test_window_rule_single_event_sends_plain_text(custom_rule) -> None:
    custom_rule("t_window_single", Rule(False, 0.1, 0, 10))
    bot = _FakeBot()
    n = AdminNotifier(dm_pacing_sec=0.01, group_pacing_sec=0.01)
    n.bind(bot, chat_id=123)
    n.start()

    n.notify("t_window_single", "solo event")
    await asyncio.sleep(0.25)

    assert bot.sent == ["solo event"]


async def test_retry_after_is_respected_then_message_still_sent(custom_rule) -> None:
    custom_rule("t_retry", Rule(True, 0, 0, 10))
    bot = _FakeBot(fail_times=1, retry_after=0.05)
    n = AdminNotifier(dm_pacing_sec=0.01, group_pacing_sec=0.01)
    n.bind(bot, chat_id=123)
    n.start()

    n.notify("t_retry", "eventually")
    await asyncio.sleep(0.25)

    assert bot.sent == ["eventually"]


async def test_notify_without_chat_id_does_nothing() -> None:
    bot = _FakeBot()
    n = AdminNotifier(dm_pacing_sec=0.01, group_pacing_sec=0.01)
    n.bind(bot, chat_id=0)
    n.start()

    n.notify("boot", "should not send")
    await asyncio.sleep(0.05)

    assert bot.sent == []


def test_real_rules_declared_for_all_documented_kinds() -> None:
    for kind in ("boot", "provider_quota", "error", "token_low", "queue_long", "payment"):
        assert kind in RULES
