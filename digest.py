"""
Еженедельный ИТ-дайджест Markformelle.
Запускается каждый понедельник в 09:00 через cron.
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
BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL")
DIGEST_TELEGRAM_CHAT_ID = os.getenv("DIGEST_TELEGRAM_CHAT_ID", "780994722")
DIGEST_BITRIX_CHAT_ID = os.getenv("DIGEST_BITRIX_CHAT_ID", "")
SNAPSHOT_FILE = os.path.join(os.path.dirname(__file__), "digest_snapshot.json")

GROUPS_SQL = """
    CASE
        WHEN GROUP_ID IN (328) THEN 'WEB'
        WHEN GROUP_ID IN (342) THEN '1С'
        WHEN GROUP_ID IN (527, 353) THEN 'ПРОИЗВОДСТВО'
        WHEN GROUP_ID = 102 THEN 'ТП'
        ELSE 'ДРУГОЕ'
    END
"""

# Контекст команд для LLM
TEAM_CONTEXT = """
Команды ИТ-отдела Markformelle (производитель одежды, Беларусь):
- WEB: ~5 разработчиков, веб-сайт, маркетплейсы (WB, Ozon, Yandex), интеграции
- 1С: ~5 разработчиков + аналитики, учётные системы, розница, склад
- ПРОИЗВОДСТВО: ~3 разработчика, производственные системы, автоматизация
- ТП (техподдержка): ~12 сотрудников, сопровождение розницы + системное администрирование

Нормативы:
- WIP/чел норма: до 5 задач на человека
- Просрочка >30 дней — критичная зона
- Возвраты >5/нед — проблема с качеством
- Throughput <10 задач/нед на группу — низкая скорость
"""


def get_week_dates():
    today = date.today()
    week_ago = today - timedelta(days=7)
    return week_ago.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')


def load_snapshot():
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_snapshot(data: dict):
    snapshot = {
        'date': date.today().strftime('%Y-%m-%d'),
        'active_by_group': data.get('active_by_group', {}),
        'overdue_by_group': data.get('overdue_by_group', {}),
        'long_tasks': data.get('long_tasks', {}),
        'tp_unassigned': data.get('tp_unassigned', {}),
    }
    with open(SNAPSHOT_FILE, 'w') as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)


def collect_data():
    from db import get_connection
    conn = get_connection()
    data = {}
    week_ago, today = get_week_dates()

    with conn.cursor() as cur:

        # 1. Задачи в работе по группам
        cur.execute(f"""
            SELECT {GROUPS_SQL} as grp, COUNT(*) as cnt
            FROM b_tasks
            WHERE GROUP_ID IN (328, 342, 527, 353, 102) AND STATUS IN (1, 2, 3)
            AND (GROUP_ID != 102 OR RESPONSIBLE_ID IN (1363,833,37985,114682,110487,107252,59940,64513,16522,119302,98217,98948,97441,93323,106080,80992))
            GROUP BY grp
        """)
        data['active_by_group'] = {r['grp']: r['cnt'] for r in cur.fetchall()}

        # 2. Просрочка по группам
        cur.execute(f"""
            SELECT {GROUPS_SQL} as grp,
                SUM(CASE WHEN DATEDIFF(NOW(), CREATED_DATE) > 7 THEN 1 ELSE 0 END) as over_7,
                SUM(CASE WHEN DATEDIFF(NOW(), CREATED_DATE) > 30 THEN 1 ELSE 0 END) as over_30,
                SUM(CASE WHEN DATEDIFF(NOW(), CREATED_DATE) > 90 THEN 1 ELSE 0 END) as over_90
            FROM b_tasks
            WHERE GROUP_ID IN (328, 342, 527, 353, 102)
            AND STATUS IN (1, 2, 3) AND DEADLINE IS NOT NULL AND DEADLINE < NOW()
            AND (GROUP_ID != 102 OR RESPONSIBLE_ID IN (1363,833,37985,114682,110487,107252,59940,64513,16522,119302,98217,98948,97441,93323,106080,80992))
            GROUP BY grp
        """)
        data['overdue_by_group'] = {r['grp']: {'over_7': int(r['over_7'] or 0), 'over_30': int(r['over_30'] or 0), 'over_90': int(r['over_90'] or 0)} for r in cur.fetchall()}

        # 3. Закрытые за неделю
        cur.execute(f"""
            SELECT {GROUPS_SQL} as grp, COUNT(*) as cnt
            FROM b_tasks
            WHERE GROUP_ID IN (328, 342, 527, 353, 102) AND STATUS = 5 AND CLOSED_DATE >= %s
            GROUP BY grp
        """, [week_ago])
        data['closed_week'] = {r['grp']: r['cnt'] for r in cur.fetchall()}

        # 4. Часы за неделю
        cur.execute(f"""
            SELECT {GROUPS_SQL.replace('GROUP_ID', 't.GROUP_ID')} as grp,
                ROUND(SUM(e.MINUTES) / 60, 1) as hours
            FROM b_tasks_elapsed_time e
            JOIN b_tasks t ON t.ID = e.TASK_ID
            WHERE t.GROUP_ID IN (328, 342, 527, 353, 102) AND e.CREATED_DATE >= %s
            GROUP BY grp
        """, [week_ago])
        data['hours_week'] = {r['grp']: float(r['hours'] or 0) for r in cur.fetchall()}

        # 5. Возвраты за неделю
        cur.execute(f"""
            SELECT {GROUPS_SQL.replace('GROUP_ID', 't.GROUP_ID')} as grp, COUNT(*) as cnt
            FROM b_tasks_log tl
            JOIN b_tasks t ON t.ID = tl.TASK_ID
            WHERE tl.FIELD = 'STAGE'
            AND tl.TO_VALUE IN ('Правки/Доработки', 'Возврат на доработку', 'На доработке')
            AND tl.CREATED_DATE >= %s AND t.GROUP_ID IN (328, 342, 527, 353)
            GROUP BY grp
        """, [week_ago])
        data['returns_week'] = {r['grp']: r['cnt'] for r in cur.fetchall()}

        # 6. ТП нераспределённые
        cur.execute("""
            SELECT COUNT(*) as cnt,
                   SUM(CASE WHEN DATEDIFF(NOW(), CREATED_DATE) > 2 THEN 1 ELSE 0 END) as old_cnt,
                   MAX(DATEDIFF(NOW(), CREATED_DATE)) as max_days
            FROM b_tasks t
            WHERE t.GROUP_ID = 102 AND t.STATUS IN (1, 2, 3) AND t.STAGE_ID = 0
            AND EXISTS (
                SELECT 1 FROM b_tasks_member m
                WHERE m.TASK_ID = t.ID AND m.TYPE IN ('A','C')
                AND m.USER_ID IN (1363,833,37985,114682,110487,107252,59940,64513,16522,119302,98217,98948,97441,93323,106080,80992)
            )
        """)
        r = cur.fetchone()
        data['tp_unassigned'] = {'total': int(r['cnt'] or 0), 'old': int(r['old_cnt'] or 0), 'max_days': int(r['max_days'] or 0)}

        # 7. Долгие задачи >30 дней
        cur.execute(f"""
            SELECT {GROUPS_SQL} as grp, COUNT(*) as cnt, MAX(DATEDIFF(NOW(), CREATED_DATE)) as max_days
            FROM b_tasks
            WHERE GROUP_ID IN (328, 342, 527, 353, 102)
            AND STATUS IN (1, 2, 3) AND DATEDIFF(NOW(), CREATED_DATE) > 30
            AND (GROUP_ID != 102 OR RESPONSIBLE_ID IN (1363,833,37985,114682,110487,107252,59940,64513,16522,119302,98217,98948,97441,93323,106080,80992))
            GROUP BY grp
        """)
        data['long_tasks'] = {r['grp']: {'cnt': r['cnt'], 'max_days': int(r['max_days'] or 0)} for r in cur.fetchall()}

        # 8. Люди по группам
        cur.execute(f"""
            SELECT {GROUPS_SQL} as grp, COUNT(DISTINCT RESPONSIBLE_ID) as people
            FROM b_tasks WHERE GROUP_ID IN (328, 342, 527, 353, 102) AND STATUS IN (1, 2, 3)
            AND (GROUP_ID != 102 OR RESPONSIBLE_ID IN (1363,833,37985,114682,110487,107252,59940,64513,16522,119302,98217,98948,97441,93323,106080,80992))
            GROUP BY grp
        """)
        data['people_by_group'] = {r['grp']: r['people'] for r in cur.fetchall()}

        # 9. ТОП-5 по закрытым задачам за неделю по каждой группе
        top5 = {}
        for grp, gids in [('WEB', [328]), ('1С', [342]), ('ПРОИЗВОДСТВО', [527, 353])]:
            ph = ','.join(['%s'] * len(gids))
            cur.execute(f"""
                SELECT CONCAT(COALESCE(u.LAST_NAME,''),' ',COALESCE(u.NAME,'')) as name,
                       COUNT(*) as cnt
                FROM b_tasks t JOIN b_user u ON u.ID = t.RESPONSIBLE_ID
                WHERE t.GROUP_ID IN ({ph}) AND t.STATUS = 5 AND t.CLOSED_DATE >= %s
                GROUP BY t.RESPONSIBLE_ID, u.LAST_NAME, u.NAME
                ORDER BY cnt DESC LIMIT 5
            """, gids + [week_ago])
            top5[grp] = [{'name': r['name'].strip(), 'cnt': r['cnt']} for r in cur.fetchall()]

        # ТП — по закрытым
        cur.execute("""
            SELECT CONCAT(COALESCE(u.LAST_NAME,''),' ',COALESCE(u.NAME,'')) as name,
                   COUNT(*) as cnt
            FROM b_tasks t JOIN b_user u ON u.ID = t.RESPONSIBLE_ID
            WHERE t.GROUP_ID = 102 AND t.STATUS = 5 AND t.CLOSED_DATE >= %s
            GROUP BY t.RESPONSIBLE_ID, u.LAST_NAME, u.NAME
            ORDER BY cnt DESC LIMIT 5
        """, [week_ago])
        top5['ТП'] = [{'name': r['name'].strip(), 'cnt': r['cnt']} for r in cur.fetchall()]
        data['top5_closed'] = top5

    conn.close()
    return data


def format_data_for_llm(data: dict, prev: dict) -> str:
    week_ago, today = get_week_dates()
    groups = ['WEB', '1С', 'ПРОИЗВОДСТВО', 'ТП']

    def delta(current, previous, key):
        if not previous:
            return ''
        cur_val = current.get(key, 0) if isinstance(current, dict) else current
        prev_val = previous.get(key, 0) if isinstance(previous, dict) else previous
        diff = cur_val - prev_val
        if diff > 0:
            return f' (+{diff} vs прошлая нед)'
        elif diff < 0:
            return f' ({diff} vs прошлая нед)'
        return ' (без изм.)'

    lines = [f"Данные ИТ-отдела Markformelle за {week_ago} — {today}\n"]
    prev_active = prev.get('active_by_group', {})
    prev_overdue = prev.get('overdue_by_group', {})

    lines.append("## ЗАДАЧИ В РАБОТЕ (WIP)")
    for g in groups:
        active = data['active_by_group'].get(g, 0)
        people = data['people_by_group'].get(g, 1)
        wip = round(active / people, 1) if people else 0
        d = delta(active, prev_active.get(g, active), None)
        lines.append(f"  {g}: {active} задач{d}, {people} чел., WIP/чел={wip}")

    lines.append("\n## ПРОСРОЧКА")
    for g in groups:
        od = data['overdue_by_group'].get(g, {})
        prev_od = prev_overdue.get(g, {})
        if od:
            d7 = int(od.get('over_7', 0))
            d30 = int(od.get('over_30', 0))
            d90 = int(od.get('over_90', 0))
            pd30 = int(prev_od.get('over_30', d30))
            diff30 = f' (+{d30-pd30})' if d30 > pd30 else (f' ({d30-pd30})' if d30 < pd30 else '')
            lines.append(f"  {g}: >7дн={d7}, >30дн={d30}{diff30}, >90дн={d90}")
        else:
            lines.append(f"  {g}: просрочки нет")

    lines.append("\n## ЗАКРЫТО ЗА НЕДЕЛЮ (Throughput)")
    for g in groups:
        lines.append(f"  {g}: {data['closed_week'].get(g, 0)} задач")

    lines.append("\n## ТОП-5 ПО ЗАКРЫТЫМ ЗАДАЧАМ ЗА НЕДЕЛЮ")
    for g in groups:
        top = data.get('top5_closed', {}).get(g, [])
        if top:
            entries = ', '.join(f"{x['name']} ({x['cnt']})" for x in top)
            lines.append(f"  {g}: {entries}")

    lines.append("\n## ЧАСЫ СПИСАНИЯ ЗА НЕДЕЛЮ")
    for g in groups:
        lines.append(f"  {g}: {data['hours_week'].get(g, 0)} ч")

    lines.append("\n## ВОЗВРАТЫ НА ДОРАБОТКУ ЗА НЕДЕЛЮ")
    for g in ['WEB', '1С', 'ПРОИЗВОДСТВО']:
        lines.append(f"  {g}: {data['returns_week'].get(g, 0)} возвратов")

    lines.append("\n## ДОЛГИЕ ЗАДАЧИ (>30 дней в работе)")
    for g in groups:
        lt = data['long_tasks'].get(g, {})
        prev_lt = prev.get('long_tasks', {}).get(g, {})
        if lt:
            d = delta(int(lt['cnt']), int(prev_lt.get('cnt', lt['cnt'])), None)
            lines.append(f"  {g}: {lt['cnt']} задач{d}, макс {lt['max_days']} дней")
        else:
            lines.append(f"  {g}: нет")

    tp = data['tp_unassigned']
    prev_tp = prev.get('tp_unassigned', {})
    d_tp = delta(tp['total'], prev_tp.get('total', tp['total']), None)
    lines.append(f"\n## ТП: НЕРАСПРЕДЕЛЁННЫЕ ЗАЯВКИ")
    lines.append(f"  Всего: {tp['total']}{d_tp}, из них >2 дней: {tp['old']}, макс {tp['max_days']} дней")

    return '\n'.join(lines)


def call_llm(data_text: str) -> str:
    prompt = f"""{TEAM_CONTEXT}

Напиши еженедельный ИТ-дайджест для руководства на основе данных ниже.

Структура:
📅 ИТ-Дайджест [период]

🔥 ГЛАВНЫЕ РИСКИ (требуют внимания):
— 2-4 критичных проблемы с именами сотрудников и конкретными цифрами
— Аномалии: рост очереди, WIP >5/чел, возвраты, долгострои

✅ УСПЕХИ НЕДЕЛИ:
— Кто из сотрудников закрыл больше всех (с цифрами из топ-5)
— Где очередь снизилась

📊 СВОДКА ПО ГРУППАМ (таблица):
Группа | В работе | Δ | Закрыто | Просрочка >30д | Часы
(используй Δ для динамики: +/- vs прошлая неделя)

💡 РЕКОМЕНДАЦИИ:
— 2-3 конкретных действия, кому и что сделать

Пиши на русском, деловым языком. Максимум 900 слов.
Используй только предоставленные данные.

ДАННЫЕ:
{data_text}"""

    response = requests.post(
        os.getenv("TOGETHER_BASE_URL", "https://api.together.xyz/v1") + "/chat/completions",
        headers={
            "Authorization": f"Bearer {os.getenv('TOGETHER_API_KEY')}",
            "Content-Type": "application/json",
        },
        json={
            "model": "qwen/qwen3-next-80b-a3b-thinking",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2500,
            "temperature": 0.6,
        },
        timeout=90,
    )
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content']


def send_telegram(chat_id: str, text: str):
    if not text:
        print(f'send_telegram: пустой текст, пропускаем')
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Убираем markdown таблицы — Telegram их не рендерит
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }, proxies={"http": None, "https": None})
        if not r.ok:
            # Попробуем без markdown
            requests.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }, proxies={"http": None, "https": None})


def send_bitrix_chat(chat_id: str, text: str):
    if not chat_id or not BITRIX_WEBHOOK_URL:
        return
    clean = text.replace('**', '').replace('*', '').replace('_', '').replace('`', '').replace('#', '')
    requests.post(
        f"{BITRIX_WEBHOOK_URL}im.message.add.json",
        json={"DIALOG_ID": chat_id, "MESSAGE": clean},
        proxies={"http": None, "https": None},
        timeout=30,
    )


def run_digest():
    print(f"[{datetime.now()}] Запуск дайджеста...")
    try:
        prev_snapshot = load_snapshot()
        data = collect_data()
        print("Данные собраны.")
        data_text = format_data_for_llm(data, prev_snapshot)
        print("Данные отформатированы, отправляем в LLM...")
        digest_text = call_llm(data_text)
        print("Дайджест получен.")

        send_telegram(DIGEST_TELEGRAM_CHAT_ID, digest_text)
        print(f"Отправлено в Telegram ({DIGEST_TELEGRAM_CHAT_ID})")

        if DIGEST_BITRIX_CHAT_ID:
            send_bitrix_chat(DIGEST_BITRIX_CHAT_ID, digest_text)
            print(f"Дублировано в Bitrix24 ({DIGEST_BITRIX_CHAT_ID})")

        save_snapshot(data)
        print("Снапшот сохранён.")
        print("Готово!")
    except Exception as e:
        print(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_digest()
