"""Минимальные unit-тесты для критических функций безопасности МОЛВИ."""
from __future__ import annotations

import time
import secrets as _secrets
import sys
import os

# Изолируем от реального .env — тесты работают без Railway/Telegram
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0:test")
os.environ.setdefault("SALUTESPEECH_AUTH_KEY", "test")
os.environ.setdefault("GIGACHAT_AUTH_KEY", "test")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ──────────────────────────────────────────────────────────────────────
# 1. Брутфорс-защита (server.py)
# ──────────────────────────────────────────────────────────────────────
from bot.api.server import _fail_log, _is_rate_limited, _record_fail, _record_success


def _reset_fails(ip: str) -> None:
    _fail_log.pop(ip, None)


def test_rate_limit_not_triggered_initially() -> None:
    _reset_fails("1.2.3.4")
    assert not _is_rate_limited("1.2.3.4")


def test_rate_limit_triggered_after_5_fails() -> None:
    ip = "5.5.5.5"
    _reset_fails(ip)
    for _ in range(5):
        _record_fail(ip)
    assert _is_rate_limited(ip)


def test_rate_limit_cleared_after_success() -> None:
    ip = "6.6.6.6"
    _reset_fails(ip)
    for _ in range(5):
        _record_fail(ip)
    assert _is_rate_limited(ip)
    _record_success(ip)
    assert not _is_rate_limited(ip)


def test_rate_limit_expires_after_window() -> None:
    ip = "7.7.7.7"
    _reset_fails(ip)
    for _ in range(5):
        _record_fail(ip)
    # Подделываем время — переносим first_ts в прошлое
    count, _ = _fail_log[ip]
    _fail_log[ip] = (count, time.time() - 1000)
    assert not _is_rate_limited(ip)


# ──────────────────────────────────────────────────────────────────────
# 2. Whitelist (queries.py) — нормализация username
# ──────────────────────────────────────────────────────────────────────
from bot.db.queries import _norm_username


def test_norm_username_strips_at() -> None:
    assert _norm_username("@user") == "user"


def test_norm_username_lowercases() -> None:
    assert _norm_username("User123") == "user123"


def test_norm_username_none() -> None:
    assert _norm_username(None) is None


def test_norm_username_empty() -> None:
    assert _norm_username("") is None


# ──────────────────────────────────────────────────────────────────────
# 3. Проверка размера файла (константы из config)
# ──────────────────────────────────────────────────────────────────────
from bot.config import settings


def test_max_audio_mb_positive() -> None:
    assert settings.max_audio_mb > 0


def test_max_duration_sec_positive() -> None:
    assert settings.max_duration_sec > 0


def test_file_size_limit_bytes() -> None:
    max_bytes = settings.max_audio_mb * 1024 * 1024
    assert max_bytes >= 20 * 1024 * 1024  # минимум 20 МБ


# ──────────────────────────────────────────────────────────────────────
# 4. FREE_MINUTES соответствует сайту
# ──────────────────────────────────────────────────────────────────────
from bot.services.pricing import FREE_MINUTES


def test_free_minutes_is_60() -> None:
    """Сайт анонсирует 60 минут бесплатно — бот должен давать столько же."""
    assert FREE_MINUTES == 60, f"FREE_MINUTES={FREE_MINUTES}, ожидалось 60"


# ──────────────────────────────────────────────────────────────────────
# 5. Secrets comparison (timing-safe)
# ──────────────────────────────────────────────────────────────────────
def test_compare_digest_correct() -> None:
    pw = "correct_password_123"
    assert _secrets.compare_digest(pw.encode(), pw.encode())


def test_compare_digest_wrong() -> None:
    assert not _secrets.compare_digest(b"wrong", b"correct")


# ──────────────────────────────────────────────────────────────────────
# 6. Session cleanup
# ──────────────────────────────────────────────────────────────────────
from bot.api.server import _sessions, _cleanup_sessions, _new_session


def test_session_cleanup_removes_expired() -> None:
    token = _secrets.token_urlsafe(16)
    _sessions[token] = time.time() - 1  # уже истекла
    _cleanup_sessions()
    assert token not in _sessions


def test_new_session_is_valid() -> None:
    sid = _new_session()
    assert sid in _sessions
    assert _sessions[sid] > time.time()


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  OK   {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL {fn.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(failed)
