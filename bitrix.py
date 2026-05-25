"""
Модуль для работы с API Битрикс24 через входящий вебхук.
Группы:
  WEB         = 328
  1С          = 342
  ПРОИЗВОДСТВО = 527, 353
"""

import requests
from datetime import datetime
from config import BITRIX_WEBHOOK_URL

GROUPS = {
    "WEB":          [328],
    "1С":           [342],
    "ПРОИЗВОДСТВО": [527, 353],
}
ALL_GROUP_IDS = [328, 342, 527, 353]


def _call(method: str, params: dict = None) -> dict:
    url = f"{BITRIX_WEBHOOK_URL}{method}.json"
    try:
        response = requests.post(url, json=params or {}, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def get_tasks(group: str = "ALL", filter_type: str = "important") -> dict:
    """
    Получить задачи по группе и типу фильтра.
    group: "WEB", "1С", "ПРОИЗВОДСТВО", "ALL"
    filter_type: "important" — важные (огонёк), "overdue" — важные просроченные
    """
    group_ids = ALL_GROUP_IDS if group == "ALL" else GROUPS.get(group, ALL_GROUP_IDS)

    base_filter = {
        "GROUP_ID": group_ids,
        "MARK": "P",  # только задачи с огоньком (важные)
    }

    if filter_type == "overdue":
        base_filter["STATUS"] = "5"  # статус "Просрочена"

    data = _call("tasks.task.list", {
        "filter": base_filter,
        "select": ["ID", "TITLE", "STATUS", "DEADLINE", "RESPONSIBLE_ID", "GROUP_ID", "MARK"],
        "order": {"DEADLINE": "ASC"},
        "limit": 50,
    })

    if "error" in data:
        return {"success": False, "error": data["error"]}

    tasks = data.get("result", {}).get("tasks", [])

    # Дополнительная проверка просрочки по дате (на случай если статус не обновился)
    if filter_type == "overdue":
        now = datetime.now()
        filtered = []
        for t in tasks:
            deadline = t.get("deadline", "")
            if deadline:
                try:
                    dl = datetime.strptime(deadline[:19], "%Y-%m-%dT%H:%M:%S")
                    if dl < now:
                        filtered.append(t)
                except ValueError:
                    filtered.append(t)
            else:
                filtered.append(t)
        tasks = filtered

    return {"success": True, "tasks": tasks}


def get_calendar_events(period: str = "today") -> dict:
    from datetime import timedelta
    now = datetime.now()
    date_from = now.strftime("%Y-%m-%dT00:00:00")
    date_to = (now.strftime("%Y-%m-%dT23:59:59") if period == "today"
               else (now + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59"))

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
    from datetime import timedelta
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
