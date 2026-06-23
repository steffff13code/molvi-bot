from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent.parent  # molvi-bot/

_env_file = BASE_DIR / ".env"


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

    # SaluteSpeech
    salutespeech_auth_key: str
    salutespeech_scope: str = "SALUTE_SPEECH_PERS"

    # GigaChat
    gigachat_auth_key: str
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat"

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
    free_minutes: int = 30          # бесплатный лимит расшифровки, минут
    price_per_hour: int = 50        # ₽/час (≈ 0,83 ₽/мин)

    # Админ / API
    admin_id: int = 0               # Telegram ID владельца (для /stats)
    admin_api_token: str = ""       # секрет для HTTP-API (X-Admin-Token)
    admin_password: str = ""        # пароль web-панели /admin (если пусто — используется admin_api_token)
    api_port: int = 0               # PORT от Railway; 0 = API не поднимать

    # HTTP
    sber_verify_ssl: bool = False

    # Public URLs (используются в меню/кнопках бота)
    site_url: str = "https://molvi-ai.ru/"
    landing_url: str = "https://molvi-ai.ru/transcribe/"
    bot_url: str = "https://t.me/molviai_bot"

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
        "Заполните ключи (TELEGRAM_BOT_TOKEN, SALUTESPEECH_AUTH_KEY, GIGACHAT_AUTH_KEY)."
    ) from e
