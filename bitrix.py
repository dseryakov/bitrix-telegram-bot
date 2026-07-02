import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from config import BITRIX_WEBHOOK_URL

load_dotenv()

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("ALL_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("all_proxy", None)

PORTAL_API_URL = "https://mfportal.by/site_api/v1"
PORTAL_API_LOGIN = os.getenv("PORTAL_API_LOGIN", "")
PORTAL_API_PASSWORD = os.getenv("PORTAL_API_PASSWORD", "")

GROUPS = {
    "WEB":          [328],
    "1С":           [342],
    "ПРОИЗВОДСТВО": [527, 353],
    "ТП":           [102],
}
ALL_GROUP_IDS = [328, 342, 527, 353, 102]

def get_task_tags(task_ids: list) -> dict:
    """
    Получить теги для списка задач через Portal API.
    Возвращает {task_id: [tag1, tag2, ...]} или {} при ошибке.
    """
    if not task_ids or not PORTAL_API_LOGIN:
        return {}
    # Батчи по 50 задач
    result = {}
    for i in range(0, len(task_ids), 50):
        batch = task_ids[i:i+50]
        try:
            r = requests.post(
                f"{PORTAL_API_URL}/tasks/tags/",
                json={"task_ids": [int(tid) for tid in batch]},
                auth=(PORTAL_API_LOGIN, PORTAL_API_PASSWORD),
                timeout=10,
                proxies={"http": None, "https": None},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("success"):
                for tid, tags in data.get("tasks", {}).items():
                    result[str(tid)] = tags
        except Exception as e:
            print(f"Portal API error get_task_tags: {e}")
    return result


def find_user_by_email(email: str) -> dict:
    """Найти пользователя Битрикс24 по email."""
    data = _call("user.search", {
        "filter": {"EMAIL": email}
    })
    users = data.get("result", [])
    if not users:
        return {"success": False, "error": "Пользователь не найден"}
    user = users[0]
    return {
        "success": True,
        "id": user["ID"],
        "name": f"{user.get('NAME', '')} {user.get('LAST_NAME', '')}".strip()
    }

def send_verification_code(bitrix_user_id: str, code: str) -> dict:
    """Отправить код верификации через системное уведомление Битрикс24."""
    data = _call("im.notify.system.add", {
        "TO": int(bitrix_user_id),
        "MESSAGE": f"🔐 Ваш код подтверждения для Telegram-бота: {code}\n\nКод действителен 5 минут.",
    })
    if "error" in data:
        return {"success": False, "error": data["error"]}
    return {"success": True}

def _call(method, params=None):
    url = f"{BITRIX_WEBHOOK_URL}{method}.json"
    try:
        r = requests.post(url, json=params or {}, timeout=30, proxies={"http": None, "https": None})
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"error": str(e)}

def get_tasks(group="ALL", filter_type="important", user_id="72721"):
    group_ids = ALL_GROUP_IDS if group == "ALL" else GROUPS.get(group, ALL_GROUP_IDS)
    try:
        from db import get_tasks_db
        tasks = get_tasks_db(group_ids, filter_type)
        return {"success": True, "tasks": tasks}
    except Exception as e:
        return {"success": False, "error": str(e)}

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

def get_calendar_events(period="today", user_id="72721"):
    now = datetime.now()
    date_from = now.strftime("%Y-%m-%dT00:00:00")
    date_to = (now.strftime("%Y-%m-%dT23:59:59") if period == "today"
               else (now + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59"))
    data = _call("calendar.event.get", {"type": "user", "ownerId": user_id, "from": date_from, "to": date_to})
    if "error" in data:
        return {"success": False, "error": data["error"]}
    events = sorted(data.get("result", []), key=lambda e: e.get("date_from", ""))
    return {"success": True, "events": events}

def create_meeting(title, date, time, duration_minutes, user_id="72721"):
    try:
        dt_start = datetime.strptime(f"{date} {time}", "%d.%m.%Y %H:%M")
        dt_end = dt_start + timedelta(minutes=duration_minutes)
    except ValueError:
        return {"success": False, "error": "Неверный формат даты или времени"}
    data = _call("calendar.event.add", {
        "type": "user", "ownerId": user_id, "name": title,
        "date_from": dt_start.strftime("%Y-%m-%dT%H:%M:%S"),
        "date_to": dt_end.strftime("%Y-%m-%dT%H:%M:%S"),
        "skip_time": "N",
    })
    if "error" in data:
        return {"success": False, "error": data["error"]}
    return {"success": True, "event_id": data.get("result")}
