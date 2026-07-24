"""
Еженедельные адресные уведомления руководителям групп.
Запускается каждый понедельник в 09:30 через cron (после дайджеста).
Для каждой группы собирает просроченные и долгие задачи подчинённых
и отправляет руководителю в Telegram.
"""
import os
import json
import requests
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

load_dotenv()

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
USERS_FILE = os.path.join(os.path.dirname(__file__), "users.json")

# Группы Битрикс24
GROUPS = {
    "WEB":          [328],
    "1С":           [342],
    "ПРОИЗВОДСТВО": [527, 353],
}


def load_tg_users():
    """Загружает маппинг bitrix_id → telegram_id из users.json."""
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE) as f:
        data = json.load(f)
    # {bitrix_id: telegram_chat_id}
    return {v['bitrix_id']: k for k, v in data.items()}


def get_group_leads():
    """Получает руководителей групп из ProjMan с их Telegram ID."""
    try:
        import psycopg2, psycopg2.extras
        conn = psycopg2.connect(
            'postgresql://projman:projman@localhost:5432/projman',
            options='-c client_encoding=UTF8'
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT name, last_name, b24_id, telegram_id, group_name, notify_tg
            FROM users
            WHERE group_name IS NOT NULL
            AND b24_id IS NOT NULL
            AND is_blocked = FALSE
            AND roles::jsonb ? 'ROLE_GROUP_LEAD'
        """)
        leads = [dict(r) for r in cur.fetchall()]
        conn.close()
        return leads
    except Exception as e:
        print(f"ProjMan error: {e}")
        return []


def get_group_tasks(group_ids: list):
    """Получает просроченные и долгие задачи группы из MySQL."""
    from db import get_connection
    conn = get_connection()
    ph = ','.join(['%s'] * len(group_ids))
    result = {'overdue': [], 'long': []}

    with conn.cursor() as cur:
        # Просроченные задачи (дедлайн прошёл, статус активный)
        cur.execute(f"""
            SELECT t.ID as id, t.TITLE as title,
                   CONCAT(COALESCE(u.LAST_NAME,''),' ',COALESCE(u.NAME,'')) as responsible,
                   t.DEADLINE as deadline,
                   DATEDIFF(NOW(), t.DEADLINE) as days_overdue
            FROM b_tasks t
            JOIN b_user u ON u.ID = t.RESPONSIBLE_ID
            WHERE t.GROUP_ID IN ({ph})
            AND t.STATUS IN (1, 2, 3)
            AND t.DEADLINE IS NOT NULL
            AND t.DEADLINE < NOW()
            ORDER BY days_overdue DESC
            LIMIT 10
        """, group_ids)
        for r in cur.fetchall():
            result['overdue'].append({
                'id': r['id'],
                'title': r['title'] or 'Без названия',
                'responsible': (r['responsible'] or '').strip(),
                'deadline': r['deadline'].strftime('%Y-%m-%d') if r['deadline'] else '',
                'days': int(r['days_overdue'] or 0),
            })

        # Задачи в работе >7 дней
        cur.execute(f"""
            SELECT t.ID as id, t.TITLE as title,
                   CONCAT(COALESCE(u.LAST_NAME,''),' ',COALESCE(u.NAME,'')) as responsible,
                   DATEDIFF(NOW(), t.CREATED_DATE) as days_in_work,
                   COALESCE(s.TITLE, '') as stage
            FROM b_tasks t
            JOIN b_user u ON u.ID = t.RESPONSIBLE_ID
            LEFT JOIN b_tasks_stages s ON s.ID = t.STAGE_ID
            WHERE t.GROUP_ID IN ({ph})
            AND t.STATUS IN (2, 3)
            AND DATEDIFF(NOW(), t.CREATED_DATE) > 7
            AND (s.TITLE IS NULL OR s.TITLE NOT IN ('Сделаны', 'Сделана', 'Выполнено', 'Закрыто'))
            ORDER BY days_in_work DESC
            LIMIT 10
        """, group_ids)
        for r in cur.fetchall():
            result['long'].append({
                'id': r['id'],
                'title': r['title'] or 'Без названия',
                'responsible': (r['responsible'] or '').strip(),
                'stage': r['stage'] or '',
                'days': int(r['days_in_work'] or 0),
            })

    conn.close()
    return result


def format_group_message(group_name: str, tasks: dict) -> str:
    """Форматирует сообщение для руководителя группы."""
    today = date.today().strftime('%d.%m.%Y')
    lines = [f"📋 *{group_name}* — задачи требующие внимания ({today})\n"]

    overdue = tasks['overdue']
    if overdue:
        lines.append(f"🔴 *Просроченные ({len(overdue)}):*")
        for t in overdue:
            url = f"https://mfportal.by/company/personal/user/0/tasks/task/view/{t['id']}/"
            lines.append(
                f"• [{t['title'][:50]}]({url})\n"
                "  👤 " + (' '.join(t['responsible'].split()[:2])) + f" | {t['days']} дн. просрочки | ⏰ {t['deadline']}"
            )
    else:
        lines.append("✅ *Просроченных задач нет*")

    lines.append("")

    long_tasks = tasks['long']
    if long_tasks:
        lines.append(f"⏰ *В работе >7 дней ({len(long_tasks)}):*")
        for t in long_tasks:
            url = f"https://mfportal.by/company/personal/user/0/tasks/task/view/{t['id']}/"
            stage_str = f" [{t['stage']}]" if t['stage'] else ""
            lines.append(
                f"• [{t['title'][:50]}]({url})\n"
                "  👤 " + (' '.join(t['responsible'].split()[:2])) + f" | {t['days']} дн.{stage_str}"
            )
    else:
        lines.append("✅ *Долгих задач нет*")

    return "\n".join(lines)


def send_telegram(chat_id: str, text: str):
    """Отправляет сообщение в Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }, proxies={"http": None, "https": None}, timeout=15)
        if not r.ok:
            # Без markdown если ошибка
            requests.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }, proxies={"http": None, "https": None}, timeout=15)


def run_notify():
    print(f"[{datetime.now()}] Запуск адресных уведомлений...")

    tg_users = load_tg_users()  # {bitrix_id: telegram_chat_id}
    leads = get_group_leads()

    if not leads:
        print("Нет руководителей в ProjMan")
        return

    for lead in leads:
        group_name = lead['group_name']
        b24_id = str(lead['b24_id'])
        name = f"{lead['last_name']} {lead['name']}"

        # Получаем числовой Telegram ID из users.json
        tg_chat_id = tg_users.get(b24_id)
        if not tg_chat_id:
            print(f"  {name} ({group_name}): нет Telegram ID в users.json — пропускаем")
            continue

        group_ids = GROUPS.get(group_name)
        if not group_ids:
            print(f"  {name}: группа '{group_name}' не найдена — пропускаем")
            continue

        print(f"  Формирую отчёт для {name} ({group_name})...")
        tasks = get_group_tasks(group_ids)
        message = format_group_message(group_name, tasks)

        send_telegram(tg_chat_id, message)
        print(f"  ✅ Отправлено {name} (chat_id: {tg_chat_id}): {len(tasks['overdue'])} просроч., {len(tasks['long'])} долгих")

    print("Готово!")


if __name__ == "__main__":
    run_notify()
