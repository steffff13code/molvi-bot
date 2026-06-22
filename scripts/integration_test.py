import asyncio
import os
import sys

from bot.config import settings
from bot.prompts.system_prompts import SUMMARY
from bot.services.gigachat import GigaChatClient
from bot.services.salute_speech import SaluteSpeechClient


async def run(wav_path: str) -> None:
    salute = SaluteSpeechClient(auth_key=settings.salutespeech_auth_key, scope=settings.salutespeech_scope)
    giga = GigaChatClient(auth_key=settings.gigachat_auth_key, scope=settings.gigachat_scope, model=settings.gigachat_model)

    print("1) SaluteSpeech: recognize...")
    transcript = await salute.recognize_short(wav_path)
    print("\n--- TRANSCRIPT ---\n")
    print(transcript)

    print("\n2) GigaChat: summary...")
    prompt = SUMMARY.format(transcript=transcript)
    summary = await giga.complete(system="Ты — помощник для структурирования заметок.", user=prompt)
    print("\n--- SUMMARY ---\n")
    print(summary)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/integration_test.py path/to/file.wav")
        raise SystemExit(2)
    wav = sys.argv[1]
    if not os.path.exists(wav):
        print(f"File not found: {wav}")
        raise SystemExit(2)
    asyncio.run(run(wav))

