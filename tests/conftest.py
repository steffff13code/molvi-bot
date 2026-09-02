from __future__ import annotations

import os
import sys

# CI запускает голый `pytest` (не `python -m pytest`), который не добавляет
# текущую директорию в sys.path сам — без этого `import bot...` падает с
# ModuleNotFoundError в любом тестовом модуле, кроме test_security.py
# (у него был свой локальный sys.path.insert).
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0:test")
os.environ.setdefault("SALUTESPEECH_AUTH_KEY", "test")
os.environ.setdefault("GIGACHAT_AUTH_KEY", "test")
