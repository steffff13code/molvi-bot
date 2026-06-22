from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent.parent  # molvi-bot/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
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

    # DB
    db_path: str = str(BASE_DIR / "data" / "molvi.db")

    # Limits
    max_audio_mb: int = 20
    max_duration_sec: int = 1800

    # HTTP
    sber_verify_ssl: bool = False

    # Public URLs (используются в меню/кнопках бота)
    site_url: str = "https://molvi-ai.ru/"
    landing_url: str = "https://molvi-ai.ru/transcribe/"
    bot_url: str = "https://t.me/molviai_bot"


try:
    settings = Settings()
except Exception as e:  # pragma: no cover
    # Делает ошибку запуска максимально понятной, когда .env ещё не заполнен.
    raise RuntimeError(
        "Не найден или не заполнен файл .env. "
        "Создайте 'molvi-bot/.env' из '.env.example' и заполните ключи."
    ) from e

