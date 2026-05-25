"""
Модуль для работы с API Битрикс24 через входящий вебхук.
Группы:
  WEB         = 328
  1С          = 342
  ПРОИЗВОДСТВО = 527, 353
"""

import requests
from datetime import datetime, timedelta
from config import BITRIX_WEBHOOK_URL

# ID групп
GROUPS = {
    "WEB":          [328],
    "1С":           [342],
    "ПРОИЗВОДСТВО": [527, 353],
}

# Все группы вместе
ALL_GROUP_IDS = [328, 342, 527, 353]


def _call(method: str, params: dict = None) -> dict:
    """Универсальный запрос к API Битрикс24."""
    url = f"{BITRIX_WEBHOOK_URL}{method}.json"
    try:
        response = requests.post(url, json=params or {}, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def get_my_tasks(group: str = "ALL") -> dict:
    """
    Получить задачи по группе.
    group: "WEB", "1С", "ПРОИЗВОДСТВО" или "ALL"
    """
    if group == "ALL":
        group_ids = ALL_GROUP_IDS
    else:
        group_ids = GROUPS.get(group, ALL_GROUP_IDS)

    data = _call("tasks.task.list", {
        "filter": {
            "GROUP_ID": group_ids,
        },
        "select": ["ID", "TITLE", "STATUS", "DEADLINE", "RESPONSIBLE_ID", "GROUP_ID", "CREATED_BY"],
        "order": {"DEADLINE": "ASC"},
        "limit": 50,
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
    events.sort(key=lambda e: e.get("date_from", ""))
    return {"success": True, "events": events}


def create_meeting(title: str, date: str, time: str, duration_minutes: int) -> dict:
    """
    Создать встречу в календаре Битрикс24.
    date: "ДД.ММ.ГГГГ"
    time: "ЧЧ:ММ"
    """
    try:
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
