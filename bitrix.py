"""
Модуль для работы с API Битрикс24 через входящий вебхук.
"""

import requests
from datetime import datetime, timedelta
from config import BITRIX_WEBHOOK_URL


def _call(method: str, params: dict = None) -> dict:
    """Универсальный запрос к API Битрикс24."""
    url = f"{BITRIX_WEBHOOK_URL}{method}.json"
    try:
        response = requests.post(url, json=params or {}, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def get_my_tasks() -> dict:
    """
    Получить задачи текущего пользователя.
    Возвращает: {"success": True, "tasks": [...]} или {"success": False, "error": "..."}
    """
    data = _call("tasks.task.list", {
        "filter": {
            "RESPONSIBLE_ID": "me",   # только мои задачи
            "STATUS": [1, 2, 3, 6],   # новые, в работе, ждут контроля, отложены
        },
        "select": ["ID", "TITLE", "STATUS", "DEADLINE", "PRIORITY"],
        "order": {"DEADLINE": "ASC"},
    })

    if "error" in data:
        return {"success": False, "error": data["error"]}

    tasks = data.get("result", {}).get("tasks", [])
    return {"success": True, "tasks": tasks}


def get_calendar_events(period: str = "today") -> dict:
    """
    Получить события календаря.
    period: "today" — только сегодня, "week" — ближайшие 7 дней.
    """
    now = datetime.now()
    date_from = now.strftime("%Y-%m-%dT00:00:00")

    if period == "today":
        date_to = now.strftime("%Y-%m-%dT23:59:59")
    else:
        date_to = (now + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59")

    data = _call("calendar.event.get", {
        "type": "user",
        "ownerId": "me",
        "from": date_from,
        "to": date_to,
    })

    if "error" in data:
        return {"success": False, "error": data["error"]}

    events = data.get("result", [])
    # Сортируем по дате начала
    events.sort(key=lambda e: e.get("date_from", ""))
    return {"success": True, "events": events}


def create_meeting(title: str, date: str, time: str, duration_minutes: int) -> dict:
    """
    Создать встречу в календаре Битрикс24.
    date: "ДД.ММ.ГГГГ"
    time: "ЧЧ:ММ"
    duration_minutes: продолжительность в минутах
    """
    try:
        # Парсим дату и время
        dt_start = datetime.strptime(f"{date} {time}", "%d.%m.%Y %H:%M")
        dt_end = dt_start + timedelta(minutes=duration_minutes)

        date_from = dt_start.strftime("%Y-%m-%dT%H:%M:%S")
        date_to = dt_end.strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return {"success": False, "error": "Неверный формат даты или времени"}

    data = _call("calendar.event.add", {
        "type": "user",
        "ownerId": "me",
        "name": title,
        "date_from": date_from,
        "date_to": date_to,
        "skip_time": "N",
    })

    if "error" in data:
        return {"success": False, "error": data["error"]}

    return {"success": True, "event_id": data.get("result")}
