"""
Хранение привязки Telegram ID → Битрикс24 ID
Данные сохраняются в файл users.json
"""

import json
import os

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