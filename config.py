"""
Настройки бота.
Токены читаются из файла .env (через python-dotenv).
"""

import os
from dotenv import load_dotenv

load_dotenv()  # загружает переменные из файла .env

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL")

# Проверяем, что оба токена заполнены
if not TELEGRAM_TOKEN:
    raise ValueError("❌ Не задан TELEGRAM_TOKEN в файле .env")

if not BITRIX_WEBHOOK_URL:
    raise ValueError("❌ Не задан BITRIX_WEBHOOK_URL в файле .env")
