"""
Аналитика задач Битрикс24.
Быстрый и полный анализ по группам.
"""

import requests
from datetime import datetime, timedelta
from config import BITRIX_WEBHOOK_URL

GROUPS = {
    "WEB":          [328],
    "1С":           [342],
    "ПРОИЗВОДСТВО": [527, 353],
    "ALL":          [328, 342, 527, 353],
}

RETURN_STAGES = [9705, 13613, 17892, 17893]
PROBLEM_KEYWORDS = ["баг", "bug", "ошибка", "проблема", "не работает", "сломал", "критич"]
ROLE_KEYWORDS = {
    "analyst":   ["аналитик"],
    "developer": ["программист", "разработч", "инженер", "teamlead", "team lead"],
    "tester":    ["тестировщик", "тестер", "qa"],
}

_user_cache = {}  # {id: position}
_user_names = {}  # {id: name}


def _call(method, params=None):
    url = f"{BITRIX_WEBHOOK_URL}{method}.json"
    try:
        r = requests.post(url, json=params or {}, timeout=30, proxies={"http": None, "https": None})
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def get_role(work_position):
    pos = (work_position or "").lower()
    for role, keywords in ROLE_KEYWORDS.items():
        if any(k in pos for k in keywords):
            return role
    return "other"


def load_user_cache():
    """Загрузить всех пользователей с должностями и именами в кэш."""
    global _user_cache, _user_names
    if _user_cache:
        return _user_cache

    start = 0
    while True:
        data = _call("user.get", {
            "select": ["ID", "NAME", "LAST_NAME", "WORK_POSITION"],
            "start": start,
        })
        users = data.get("result", [])
        if not users:
            break
        for u in users:
            uid = str(u["ID"])
            _user_cache[uid] = u.get("WORK_POSITION") or ""
            _user_names[uid] = f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
        total = data.get("total", 0)
        start += 50
        if start >= total:
            break

    return _user_cache


def get_participant_roles(task):
    """Получить роли участников задачи из кэша."""
    ids = set()
    ids.add(str(task.get("RESPONSIBLE_ID", "")))
    ids.add(str(task.get("CREATED_BY", "")))
    for uid in task.get("AUDITORS", []):
        ids.add(str(uid))
    for uid in task.get("ACCOMPLICES", []):
        ids.add(str(uid))
    ids.discard("")

    roles = set()
    for uid in ids:
        pos = _user_cache.get(uid, "")
        role = get_role(pos)
        if role != "other":
            roles.add(role)
    return roles


def _calc_days(created, closed):
    if not created or not closed:
        return None
    try:
        dt1 = datetime.fromisoformat(created[:19])
        dt2 = datetime.fromisoformat(closed[:19])
        return max(0, (dt2 - dt1).days)
    except Exception:
        return None


def _avg(lst):
    return round(sum(lst) / len(lst), 1) if lst else 0


def _collect_participant_ids(task):
    ids = set()
    ids.add(str(task.get("RESPONSIBLE_ID", "")))
    ids.add(str(task.get("CREATED_BY", "")))
    for uid in task.get("AUDITORS", []):
        ids.add(str(uid))
    for uid in task.get("ACCOMPLICES", []):
        ids.add(str(uid))
    ids.discard("")
    return ids


def _get_tasks_quick(group_ids, year_ago, limit=500):
    """Быстрое получение задач без доп запросов на участников."""
    all_tasks = []
    start = 0
    while True:
        data = _call("tasks.task.list", {
            "filter": {"GROUP_ID": group_ids, ">=CLOSED_DATE": year_ago},
            "select": ["ID", "CLOSED_DATE", "CREATED_DATE", "TITLE",
                       "RESPONSIBLE_ID", "CREATED_BY", "AUDITORS", "ACCOMPLICES"],
            "order": {"CLOSED_DATE": "DESC"},
            "limit": 50,
            "start": start,
        })
        if "error" in data:
            break
        tasks = data.get("result", {}).get("tasks", [])
        if not tasks:
            break
        for t in tasks:
            t["RESPONSIBLE_ID"] = t.get("responsibleId", "")
            t["CREATED_BY"] = t.get("createdBy", "")
            t["AUDITORS"] = t.get("auditors", [])
            t["ACCOMPLICES"] = t.get("accomplices", [])
        all_tasks.extend(tasks)
        total = data.get("total", 0)
        start += 50
        if start >= total or start >= limit:
            break

    return all_tasks, data.get("total", 0) if all_tasks else 0


def _process_tasks(tasks, return_counts=None):
    """Обработать задачи и вернуть статистику."""
    if return_counts is None:
        return_counts = {}
    
    with_analyst, without_analyst = [], []
    with_tester, without_tester = [], []
    analyst_stats = {}
    tester_stats = {}

    for t in tasks:
        roles = get_participant_roles(t)
        days = _calc_days(t.get("createdDate"), t.get("closedDate"))
        if days is None:
            continue

        task_id = str(t.get("id", ""))
        returns = return_counts.get(task_id, 0)

        responsible_id = str(t.get("RESPONSIBLE_ID", ""))
        accomplices = [str(uid) for uid in t.get("ACCOMPLICES", [])]

        for uid in _collect_participant_ids(t):
            pos = _user_cache.get(uid, "")
            role = get_role(pos)
            name = _user_names.get(uid, f"ID {uid}")

            if role not in ("analyst", "tester"):
                continue

            if uid == responsible_id:
                participation = "responsible"
            elif uid in accomplices:
                participation = "accomplice"
            else:
                participation = "auditor"

            stats = analyst_stats if role == "analyst" else tester_stats
            if name not in stats:
                stats[name] = {"days": [], "responsible": 0, "accomplice": 0, "auditor": 0, "returns": 0, "tasks_with_returns": 0}
            stats[name]["days"].append(days)
            stats[name][participation] += 1
            stats[name]["returns"] += returns
            if returns > 0:
                stats[name]["tasks_with_returns"] += 1

        if "analyst" in roles:
            with_analyst.append(days)
        else:
            without_analyst.append(days)

        if "tester" in roles:
            with_tester.append(days)
        else:
            without_tester.append(days)

    analyst_diff = 0
    if with_analyst and without_analyst:
        analyst_diff = round((1 - _avg(with_analyst) / max(_avg(without_analyst), 1)) * 100)

    tester_diff = 0
    if with_tester and without_tester:
        tester_diff = round((1 - _avg(with_tester) / max(_avg(without_tester), 1)) * 100)

    analyst_by_person = {
        name: {
            "count": len(s["days"]),
            "avg_days": _avg(s["days"]),
            "responsible": s["responsible"],
            "accomplice": s["accomplice"],
            "auditor": s["auditor"],
            "returns": s["returns"],
            "tasks_with_returns": s["tasks_with_returns"],
        }
        for name, s in sorted(analyst_stats.items(), key=lambda x: -len(x[1]["days"]))
    }
    tester_by_person = {
        name: {
            "count": len(s["days"]),
            "avg_days": _avg(s["days"]),
            "responsible": s["responsible"],
            "accomplice": s["accomplice"],
            "auditor": s["auditor"],
            "returns": s["returns"],
            "tasks_with_returns": s["tasks_with_returns"],
        }
        for name, s in sorted(tester_stats.items(), key=lambda x: -len(x[1]["days"]))
    }

    return {
        "analyst": {
            "with_count": len(with_analyst),
            "without_count": len(without_analyst),
            "with_avg_days": _avg(with_analyst),
            "without_avg_days": _avg(without_analyst),
            "faster_pct": analyst_diff,
            "by_person": analyst_by_person,
        },
        "tester": {
            "with_count": len(with_tester),
            "without_count": len(without_tester),
            "with_avg_days": _avg(with_tester),
            "without_avg_days": _avg(without_tester),
            "faster_pct": tester_diff,
            "by_person": tester_by_person,
        },
    }


def quick_analytics(group="ALL"):
    group_ids = GROUPS.get(group, GROUPS["ALL"])
    year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00")

    load_user_cache()
    tasks, total = _get_tasks_quick(group_ids, year_ago, limit=500)

    # Загружаем возвраты из БД
    try:
        from db import get_group_return_stats
        year_ago_db = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        return_counts = get_group_return_stats(group_ids, year_ago_db)
        total_returns = len(return_counts)
        total_return_events = sum(return_counts.values())
    except Exception:
        return_counts = {}
        total_returns = 0
        total_return_events = 0

    return_now_data = _call("tasks.task.list", {
        "filter": {"GROUP_ID": group_ids, "STAGE_ID": RETURN_STAGES},
        "select": ["ID"], "limit": 1,
    })
    return_now = return_now_data.get("total", 0)

    stats = _process_tasks(tasks, return_counts)

    return {
        "success": True,
        "type": "quick",
        "group": group,
        "total_closed": total,
        "analyzed": len(tasks),
        "return_now": return_now,
        "total_returns": total_returns,
        "total_return_events": total_return_events,
        **stats,
    }


def full_analytics(group="ALL"):
    """Полный анализ — все задачи за год."""
    group_ids = GROUPS.get(group, GROUPS["ALL"])
    year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00")

    load_user_cache()

    # Получаем все задачи
    all_tasks_basic = []
    start = 0
    while True:
        data = _call("tasks.task.list", {
            "filter": {"GROUP_ID": group_ids, ">=CLOSED_DATE": year_ago},
            "select": ["ID", "CLOSED_DATE", "CREATED_DATE", "TITLE"],
            "order": {"CLOSED_DATE": "DESC"},
            "limit": 50,
            "start": start,
        })
        if "error" in data:
            break
        tasks = data.get("result", {}).get("tasks", [])
        if not tasks:
            break
        all_tasks_basic.extend(tasks)
        total = data.get("total", 0)
        start += 50
        if start >= total or start >= 2000:
            break

    # Получаем участников для каждой задачи
    all_tasks = []
    for t in all_tasks_basic:
        members = _call("task.item.list", {
            "ORDER": {},
            "FILTER": {"ID": t["id"]},
            "PARAMS": {},
            "SELECT": ["ID", "RESPONSIBLE_ID", "CREATED_BY", "AUDITORS", "ACCOMPLICES"]
        })
        member_data = members.get("result", [{}])
        m = member_data[0] if member_data else {}
        t["RESPONSIBLE_ID"] = m.get("RESPONSIBLE_ID", "")
        t["CREATED_BY"] = m.get("CREATED_BY", "")
        t["AUDITORS"] = m.get("AUDITORS", [])
        t["ACCOMPLICES"] = m.get("ACCOMPLICES", [])
        all_tasks.append(t)

    return_now_data = _call("tasks.task.list", {
        "filter": {"GROUP_ID": group_ids, "STAGE_ID": RETURN_STAGES},
        "select": ["ID"], "limit": 1,
    })
    return_now = return_now_data.get("total", 0)

    return_year_data = _call("tasks.task.list", {
        "filter": {"GROUP_ID": group_ids, "STAGE_ID": RETURN_STAGES,
                   ">=CREATED_DATE": year_ago},
        "select": ["ID"], "limit": 1,
    })
    return_ever = return_year_data.get("total", 0)

    problem_count = sum(
        1 for t in all_tasks
        if any(k in (t.get("title") or "").lower() for k in PROBLEM_KEYWORDS)
    )

    return_pct = round(return_ever / max(len(all_tasks), 1) * 100, 1)
    stats = _process_tasks(all_tasks)

    return {
        "success": True,
        "type": "full",
        "group": group,
        "total_closed": len(all_tasks),
        "return_now": return_now,
        "return_ever": return_ever,
        "return_pct": return_pct,
        "problem_tasks": problem_count,
        **stats,
    }
def return_analytics(group="ALL"):
    """Анализ задач в стадии возврата по специалистам."""
    group_ids = GROUPS.get(group, GROUPS["ALL"])
    load_user_cache()

    # Получаем все задачи в стадии возврата
    all_return_tasks = []
    start = 0
    while True:
        data = _call("tasks.task.list", {
            "filter": {"GROUP_ID": group_ids, "STAGE_ID": RETURN_STAGES},
            "select": ["ID", "TITLE", "STAGE_ID"],
            "limit": 50,
            "start": start,
        })
        tasks = data.get("result", {}).get("tasks", [])
        if not tasks:
            break
        all_return_tasks.extend(tasks)
        total = data.get("total", 0)
        start += 50
        if start >= total:
            break

    analyst_returns = {}  # {name: count}
    tester_returns = {}
    no_specialist = 0

    for t in all_return_tasks:
        members = _call("task.item.list", {
            "ORDER": {}, "FILTER": {"ID": t["id"]}, "PARAMS": {},
            "SELECT": ["ID", "RESPONSIBLE_ID", "CREATED_BY", "AUDITORS", "ACCOMPLICES"]
        })
        m = members.get("result", [{}])[0] if members.get("result") else {}

        all_ids = set()
        all_ids.add(str(m.get("RESPONSIBLE_ID", "")))
        all_ids.add(str(m.get("CREATED_BY", "")))
        for uid in m.get("AUDITORS", []) + m.get("ACCOMPLICES", []):
            all_ids.add(str(uid))
        all_ids.discard("")

        has_specialist = False
        for uid in all_ids:
            pos = _user_cache.get(uid, "")
            role = get_role(pos)
            name = _user_names.get(uid, f"ID {uid}")
            if role == "analyst":
                analyst_returns[name] = analyst_returns.get(name, 0) + 1
                has_specialist = True
            elif role == "tester":
                tester_returns[name] = tester_returns.get(name, 0) + 1
                has_specialist = True

        if not has_specialist:
            no_specialist += 1

    return {
        "success": True,
        "total_return": len(all_return_tasks),
        "no_specialist": no_specialist,
        "analyst_returns": dict(sorted(analyst_returns.items(), key=lambda x: -x[1])),
        "tester_returns": dict(sorted(tester_returns.items(), key=lambda x: -x[1])),
    }