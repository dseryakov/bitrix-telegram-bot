from analytics import _call, load_user_cache, get_role, _user_cache, _user_names
import json

load_user_cache()

data = _call("tasks.task.list", {
    "filter": {"GROUP_ID": [328, 342, 527, 353], "STAGE_ID": [9705, 13613, 17892, 17893]},
    "select": ["ID", "TITLE", "STAGE_ID"],
    "limit": 5,
})
tasks = data.get("result", {}).get("tasks", [])
print("Всего в возврате:", data.get("total", 0))

for t in tasks:
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
    
    roles = {}
    for uid in all_ids:
        pos = _user_cache.get(uid, "")
        role = get_role(pos)
        name = _user_names.get(uid, uid)
        if role in ("analyst", "tester"):
            roles[name] = role
    
    print(f"\nЗадача {t['id']}: {t['title'][:40]}")
    print("Специалисты:", roles)