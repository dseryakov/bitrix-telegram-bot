"""
Хранение привязки Telegram ID → Битрикс24 ID
Данные сохраняются в файл users.json
"""

import json
import os
import time

CODES_FILE = "codes.json"

def save_code(telegram_id: int, code: str):
    """Сохранить код верификации с временем истечения."""
    codes = load_codes()
    codes[str(telegram_id)] = {
        "code": code,
        "expires": time.time() + 300  # 5 минут
    }
    with open(CODES_FILE, "w", encoding="utf-8") as f:
        json.dump(codes, f)

def verify_code(telegram_id: int, code: str) -> bool:
    """Проверить код верификации."""
    codes = load_codes()
    entry = codes.get(str(telegram_id))
    if not entry:
        return False
    if time.time() > entry["expires"]:
        return False
    return entry["code"] == code

def load_codes() -> dict:
    if not os.path.exists(CODES_FILE):
        return {}
    try:
        with open(CODES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

USERS_FILE = "users.json"


def load_users() -> dict:
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_users(users: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def get_bitrix_user(telegram_id: int) -> dict | None:
    """Получить данные пользователя Битрикс24 по Telegram ID."""
    users = load_users()
    return users.get(str(telegram_id))


def register_user(telegram_id: int, bitrix_id: str, name: str):
    """Сохранить привязку пользователя."""
    users = load_users()
    users[str(telegram_id)] = {"bitrix_id": bitrix_id, "name": name}
    save_users(users)