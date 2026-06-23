# Провайдеры распознавания (STT) и обработки (LLM)

Весь код вызывает провайдеров ТОЛЬКО через адаптеры в `bot/services/providers/`.
Замена провайдера = новая реализация в адаптере + переменные окружения.
Шаблоны, UX, лимиты, Вариант А — трогать НЕ нужно.

## Точки замены

| Что | Файл | Интерфейс |
|---|---|---|
| Распознавание (аудио→текст) | `bot/services/providers/stt.py` | `async transcribe(source_path: str, duration_sec: int|None) -> str` |
| Обработка (текст→саммари) | `bot/services/providers/llm.py` | `async summarize(*, text: str, system: str) -> str` |

`source_path` — исходный скачанный файл (mp3/ogg/mp4/…). Провайдер сам решает,
нужна ли конвертация (Nexara — нет; SaluteSpeech конвертирует в PCM внутри себя).

## Текущие реализации

- **STT по умолчанию: Nexara** (Whisper-совместимый). Класс `NexaraSTT`.
  Принимает файл напрямую multipart-запросом на `NEXARA_URL`.
- **STT резерв: SaluteSpeech.** Класс `SaluteSTT` (конвертирует в raw PCM, sync/async).
- **LLM: GigaChat.** Класс `GigaChatLLM`.

Выбор провайдера — в `get_stt()` / `get_llm()` по env.

## Переменные окружения

| Переменная | Назначение | Значение |
|---|---|---|
| `STT_PROVIDER` | какой STT использовать | `nexara` (по умолчанию) или `salute` |
| `NEXARA_API_KEY` | ключ Nexara | `nx-...` |
| `NEXARA_URL` | эндпоинт Nexara | по умолчанию `https://api.nexara.ru/api/v1/audio/transcriptions` |
| `LLM_PROVIDER` | какой LLM | `gigachat` |
| `SALUTESPEECH_AUTH_KEY` / `GIGACHAT_AUTH_KEY` | ключи Сбера | для резерва/LLM |

## Как добавить нового STT-провайдера

1. В `stt.py` написать класс с методом `async transcribe(source_path, duration_sec) -> str`.
   При исчерпании пакета/лимита бросать `STTQuotaError` (бот покажет понятное сообщение без ретраев).
2. Добавить ветку в `get_stt()` по значению `STT_PROVIDER`.
3. Прописать ключи в env (Railway Variables). Код вне адаптера не меняется.

## Заметки по Nexara
- Один запрос на весь файл (без async-поллинга). `response_format=verbose_json`, берём поле `text`.
- Возможны ограничения по размеру файла на стороне Nexara — текущий лимит бота `MAX_AUDIO_MB=40`.
- 402/429 → трактуются как `STTQuotaError`.
