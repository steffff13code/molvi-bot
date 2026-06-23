# МОЛВИ — Telegram-бот (MVP)

Telegram-бот «МОЛВИ»: пользователь отправляет голосовое/аудио/видео → бот распознаёт речь → по выбору отдаёт обычную расшифровку или одно из **8 структурированных саммари-шаблонов** (через GigaChat).

## Актуальная архитектура (обновлено)

- **Распознавание (STT): Nexara** (Whisper-совместимый) по умолчанию; SaluteSpeech — резерв. Переключение и ключи — через `.env`, см. **PROVIDER.md**. Слой-адаптер: `bot/services/providers/`.
- **Обработка (LLM): GigaChat.**
- **Приватность (Вариант А):** контент НЕ хранится. Файл удаляется сразу после распознавания, расшифровка живёт только в RAM на время сессии (`services/session_store.py`). В БД — только метаданные (`users`, `events`, `whitelist`).
- **Шаблоны саммари:** `bot/prompts/system_prompts.py` (8 шаблонов + обычная).
- **Лимиты/цены — единый источник** `bot/services/pricing.py` (env `FREE_MINUTES`, `PRICE_PER_HOUR`).
  > Экономика: **50 ₽/час ≈ 0,83 ₽/мин** — это НИЖЕ себестоимости Сбера для физлиц (≈ 1,2 ₽/мин = 72 ₽/час). Прибыльно на тарифе юрлица (≈ 0,6 ₽/мин = 36 ₽/час) или на собственном Whisper. Сайт — статика, цены правятся вручную под эти же значения.
- **Деплой: Railway** (см. `../DEPLOY.md`). HTTP-API для админки — `bot/api/server.py`.

Ниже — исторические заметки MVP (часть устарела: записи/`outputs` больше не хранятся, STT по умолчанию Nexara).

## Важно про секреты

Не храните токены и ключи в коде. Положите их в `.env` (файл в `.gitignore`).
Если вы уже публиковали токены/ключи где-либо — **срочно перевыпустите их**.

## Требования

- Python **3.11+**
- Установленный **ffmpeg** (нужен `pydub`)

### Установка ffmpeg (Windows)

Установите ffmpeg любым удобным способом (например, через `winget`) и убедитесь, что `ffmpeg` доступен в PATH.

## Быстрый старт (локально)

1) Перейдите в папку бота и создайте окружение:

```bash
cd molvi-bot
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

2) Создайте `.env` по примеру:

```bash
copy .env.example .env
```

Заполните `TELEGRAM_BOT_TOKEN`, `SALUTESPEECH_AUTH_KEY`, `GIGACHAT_AUTH_KEY`.

3) Запуск:

```bash
python -m bot.main
```

## Как работает обработка

- Голосовое/аудио скачивается во временную папку `audio/`
- Конвертируется в WAV PCM 16kHz mono
- Распознаётся SaluteSpeech
- Запись сохраняется в SQLite (`data/molvi.db`)
- Дальше по inline-кнопкам вызывается GigaChat, ответы кэшируются в таблице `outputs`

## Деплой рядом со статическим сайтом (рекомендация)

Если сайт статический, а бот должен работать 24/7 — нужен **всегда работающий процесс** (обычно VPS).
Бот можно держать в подпапке рядом с сайтом (например, `/var/www/site/molvi-bot`) и запускать отдельным сервисом `systemd` (см. ниже в разделе «Деплой» — будет добавлено).

## Деплой (VPS/Linux + systemd)

Пример: сайт лежит в `/var/www/molvi-site`, а бот — в `/var/www/molvi-site/molvi-bot`.

1) Установите системные зависимости:

```bash
sudo apt update
sudo apt install -y python3-venv ffmpeg
```

2) Подготовьте окружение бота:

```bash
cd /var/www/molvi-site/molvi-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните `.env` секретами.

3) Создайте unit-файл:

`/etc/systemd/system/molvi-bot.service`

```ini
[Unit]
Description=Molvi Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/var/www/molvi-site/molvi-bot
Environment=PYTHONUNBUFFERED=1
ExecStart=/var/www/molvi-site/molvi-bot/.venv/bin/python -m bot.main
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

4) Запустите и включите автозапуск:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now molvi-bot
sudo systemctl status molvi-bot
```

Логи:

```bash
journalctl -u molvi-bot -f
```

## Интеграционный тест (wav → transcript → summary)

```bash
py scripts/integration_test.py path/to/file.wav
```

## Next steps (после MVP)

- Docker + docker-compose
- PostgreSQL вместо SQLite
- Очередь задач (Redis + Celery/RQ)
- Webhook вместо long polling
- Метрики и алерты
