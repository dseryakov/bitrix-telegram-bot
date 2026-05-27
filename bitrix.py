import requests
import os
from datetime import datetime, timedelta
from config import BITRIX_WEBHOOK_URL

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("ALL_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("all_proxy", None)

GROUPS = {
    "WEB":          [328],
    "1С":           [342],
    "ПРОИЗВОДСТВО": [527, 353],
}
ALL_GROUP_IDS = [328, 342, 527, 353]

def _call(method, params=None):
    url = f"{BITRIX_WEBHOOK_URL}{method}.json"
    try:
        r = requests.post(url, json=params or {}, timeout=30, proxies={"http": None, "https": None})
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"error": str(e)}

def get_tasks(group="ALL", filter_type="important"):
    group_ids = ALL_GROUP_IDS if group == "ALL" else GROUPS.get(group, ALL_GROUP_IDS)
    if filter_type == "overdue":
        f = {"GROUP_ID": group_ids, "PRIORITY": "2", "STATUS": "5"}
    else:
        f = {"GROUP_ID": group_ids, "PRIORITY": "2", "STATUS": [1, 2, 3]}
    data = _call("tasks.task.list", {
        "filter": f,
    "select": ["ID", "TITLE", "STATUS", "DEADLINE", "GROUP_ID", "RESPONSIBLE_ID", "TIME_SPENT_IN_LOGS", "RESPONSIBLE"],
        "order": {"DEADLINE": "ASC"},
        "limit": 50,
    })
    if "error" in data:
        return {"success": False, "error": data["error"]}
    return {"success": True, "tasks": data.get("result", {}).get("tasks", [])}

def get_last_comment(task_id: str) -> str:
    """Получить последний комментарий к задаче."""
    data = _call("task.commentitem.getlist", {
        "TASK_ID": task_id,
    })
    comments = data.get("result", [])
    if not comments:
        return ""
    # Берём последний комментарий
    last = comments[-1]
    author = last.get("AUTHOR_NAME", "")
    date = last.get("POST_DATE", "")[:10]
    message = last.get("POST_MESSAGE", "")
    import re
    message = re.sub(r'\[USER=\d+\](.*?)\[\/USER\]', r'\1', message)
    message = message.strip()[:100]
    return f"{author} ({date}): {message}"

def get_calendar_events(period="today"):
    now = datetime.now()
    date_from = now.strftime("%Y-%m-%dT00:00:00")
    date_to = (now.strftime("%Y-%m-%dT23:59:59") if period == "today"
               else (now + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59"))
    data = _call("calendar.event.get", {"type": "user", "ownerId": "me", "from": date_from, "to": date_to})
    if "error" in data:
        return {"success": False, "error": data["error"]}
    events = sorted(data.get("result", []), key=lambda e: e.get("date_from", ""))
    return {"success": True, "events": events}

def create_meeting(title, date, time, duration_minutes):
    try:
        dt_start = datetime.strptime(f"{date} {time}", "%d.%m.%Y %H:%M")
        dt_end = dt_start + timedelta(minutes=duration_minutes)
    except ValueError:
        return {"success": False, "error": "Неверный формат даты или времени"}
    data = _call("calendar.event.add", {
        "type": "user", "ownerId": "me", "name": title,
        "date_from": dt_start.strftime("%Y-%m-%dT%H:%M:%S"),
        "date_to": dt_end.strftime("%Y-%m-%dT%H:%M:%S"),
        "skip_time": "N",
    })
    if "error" in data:
        return {"success": False, "error": data["error"]}
    return {"success": True, "event_id": data.get("result")}
