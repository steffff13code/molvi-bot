from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent.parent  # molvi-bot/

_env_file = BASE_DIR / ".env"

# Bot API отдаёт боту файлы не более 20 МБ (core.telegram.org/bots/faq). Значение из env
# может только уменьшать эффективный лимит, никогда не увеличивать его.
TELEGRAM_DOWNLOAD_LIMIT_MB = 20

# До PR-6 обрезка (trim_audio) шла через pydub — вся запись грузилась в память,
# на ~30 мин пиковый RSS доходил до ~4 ГБ. С PR-6 обрезка идёт через ffmpeg
# (-c copy, без декодирования, память O(1)) — реальной технической причины
# держать потолок в 1800 с больше нет. 7200 с (2 часа) — рабочий потолок,
# согласованный с владельцем как следующее значение MAX_DURATION_SEC на Railway;
# значение из env может только уменьшать эффективный лимит, не увеличивать его.
MAX_DURATION_HARD_CEILING_SEC = 7200


def _default_db_path() -> str:
    """БД по умолчанию рядом с проектом.

    На Railway файловая система эфемерна (стирается при каждом деплое),
    поэтому в проде путь переопределяется переменной окружения DB_PATH,
    указывающей на смонтированный Volume (например, /data/molvi.db).
    """
    return str(BASE_DIR / "data" / "molvi.db")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_env_file) if _env_file.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str

    # SaluteSpeech (опциональный резервный STT — нужен только при STT_PROVIDER=salute)
    salutespeech_auth_key: str = ""
    salutespeech_scope: str = "SALUTE_SPEECH_PERS"

    # GigaChat
    gigachat_auth_key: str
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat-2-Pro"
    gigachat_streams: int = 1       # физлицу GigaChat даёт ровно 1 поток; ИП-тариф — отдельное решение

    # Провайдеры (swap-ready, см. PROVIDER.md).
    stt_provider: str = "nexara"        # nexara | salute
    llm_provider: str = "gigachat"

    # Nexara (Whisper-совместимый STT, принимает файл напрямую)
    nexara_api_key: str = ""
    nexara_url: str = "https://api.nexara.ru/api/v1/audio/transcriptions"

    # DB — путь переопределяется через DB_PATH (Railway Volume в проде)
    db_path: str = ""

    # Limits
    max_audio_mb: int = 20
    max_duration_sec: int = 1800

    # Тарифы / лимиты (единый источник правды, см. services/pricing.py)
    free_minutes: int = 60          # бесплатный лимит расшифровки, минут
    price_per_hour: int = 50        # ₽/час (≈ 0,83 ₽/мин)
    template_runs_limit: int = 3    # разных шаблонов на одну запись без доплаты
    records_retention_days: int = 30  # хранение текста расшифровки в «Моих записях»

    # Админ / API
    admin_id: int = 0               # Telegram ID владельца (для /stats)
    admin_chat_id: int = 0          # куда слать уведомления AdminNotifier; 0 = admin_id
    heartbeat_url: str = ""         # внешний монитор — пинг раз в 300с, только пока polling жив
    admin_api_token: str = ""       # секрет для HTTP-API (X-Admin-Token)
    admin_password_hash: str = ""   # bcrypt-хеш пароля web-панели (предпочтительно)
    admin_password: str = ""        # plaintext-пароль (legacy; используется если hash не задан)
    api_port: int = 0               # PORT от Railway; 0 = API не поднимать

    # HTTP — канал, по которому уходят ПОЛНЫЕ расшифровки (включая шаблоны вроде
    # «Сессия с психологом») и долгоживущий клиентский секрет GigaChat. verify=False
    # отключает и проверку цепочки, и проверку имени хоста — никогда не по умолчанию.
    sber_verify_ssl: bool = True
    sber_ca_bundle: str = ""      # путь к CA-бандлу НУЦ Минцифры; пусто = системный certifi

    # Public URLs (используются в меню/кнопках бота)
    site_url: str = "https://molvi-ai.ru/"
    landing_url: str = "https://molvi-ai.ru/transcribe/"
    bot_url: str = "https://t.me/molviai_bot"

    @property
    def effective_max_mb(self) -> int:
        """Реальный лимит файла: env может только УМЕНЬШИТЬ 20 МБ, не увеличить —
        Telegram Bot API (getFile) не отдаёт боту файлы больше этого порога."""
        return min(self.max_audio_mb, TELEGRAM_DOWNLOAD_LIMIT_MB)

    @property
    def effective_max_duration_sec(self) -> int:
        """Реальный лимит длительности: env может только УМЕНЬШИТЬ 7200 с, не увеличить."""
        return min(self.max_duration_sec, MAX_DURATION_HARD_CEILING_SEC)

    def model_post_init(self, __context: object) -> None:
        # DB_PATH из окружения имеет приоритет; иначе — путь по умолчанию.
        if not self.db_path:
            object.__setattr__(self, "db_path", os.getenv("DB_PATH") or _default_db_path())
        # Railway отдаёт порт в переменной PORT — поднимаем на нём API.
        if not self.api_port:
            port_env = os.getenv("PORT")
            if port_env and port_env.isdigit():
                object.__setattr__(self, "api_port", int(port_env))


try:
    settings = Settings()
except Exception as e:  # pragma: no cover
    raise RuntimeError(
        "Не найден или не заполнен файл .env / переменные окружения. "
        "Заполните ключи (TELEGRAM_BOT_TOKEN, GIGACHAT_AUTH_KEY; "
        "SALUTESPEECH_AUTH_KEY нужен только при STT_PROVIDER=salute)."
    ) from e


def sber_verify() -> bool | str:
    """True | путь к CA-бандлу. Никогда не False — httpx(verify=...) для oauth.py
    и gigachat.py, канал с полными расшифровками пользователей."""
    p = settings.sber_ca_bundle
    return p if p and os.path.exists(p) else True
