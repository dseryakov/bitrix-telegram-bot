"""
Еженедельный ИТ-дайджест.
Запускается по расписанию (cron) каждый понедельник в 09:00.
Собирает данные из MySQL Битрикс24, отправляет в Claude API для анализа,
результат публикует в Telegram и Bitrix24.
"""
import os
import sys
import asyncio
import requests
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

load_dotenv()

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL")

# Куда слать дайджест (настраивается)
DIGEST_TELEGRAM_CHAT_ID = os.getenv("DIGEST_TELEGRAM_CHAT_ID", "780994722")  # ваш личный ID для теста
DIGEST_BITRIX_CHAT_ID = os.getenv("DIGEST_BITRIX_CHAT_ID", "")  # ID группового чата Bitrix24


def get_week_dates():
    today = date.today()
    week_ago = today - timedelta(days=7)
    return week_ago.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')


def collect_data():
    """Собирает все данные из MySQL для дайджеста."""
    from db import get_connection
    conn = get_connection()
    data = {}
    week_ago, today = get_week_dates()

    with conn.cursor() as cur:
        # 1. Задачи в работе по группам
        cur.execute("""
            SELECT
                CASE
                    WHEN GROUP_ID IN (328) THEN 'WEB'
                    WHEN GROUP_ID IN (342) THEN '1С'
                    WHEN GROUP_ID IN (527, 353) THEN 'ПРОИЗВОДСТВО'
                    WHEN GROUP_ID = 102 THEN 'ТП'
                    ELSE 'ДРУГОЕ'
                END as grp,
                COUNT(*) as cnt
            FROM b_tasks
            WHERE GROUP_ID IN (328, 342, 527, 353, 102)
            AND STATUS IN (1, 2, 3)
            GROUP BY grp
        """)
        data['active_by_group'] = {r['grp']: r['cnt'] for r in cur.fetchall()}

        # 2. Просрочка по группам (>7 дней, >30 дней, >90 дней)
        cur.execute("""
            SELECT
                CASE
                    WHEN GROUP_ID IN (328) THEN 'WEB'
                    WHEN GROUP_ID IN (342) THEN '1С'
                    WHEN GROUP_ID IN (527, 353) THEN 'ПРОИЗВОДСТВО'
                    WHEN GROUP_ID = 102 THEN 'ТП'
                    ELSE 'ДРУГОЕ'
                END as grp,
                SUM(CASE WHEN DATEDIFF(NOW(), CREATED_DATE) > 7 THEN 1 ELSE 0 END) as over_7,
                SUM(CASE WHEN DATEDIFF(NOW(), CREATED_DATE) > 30 THEN 1 ELSE 0 END) as over_30,
                SUM(CASE WHEN DATEDIFF(NOW(), CREATED_DATE) > 90 THEN 1 ELSE 0 END) as over_90
            FROM b_tasks
            WHERE GROUP_ID IN (328, 342, 527, 353, 102)
            AND STATUS IN (1, 2, 3)
            AND DEADLINE IS NOT NULL AND DEADLINE < NOW()
            GROUP BY grp
        """)
        data['overdue_by_group'] = {r['grp']: {'over_7': r['over_7'], 'over_30': r['over_30'], 'over_90': r['over_90']} for r in cur.fetchall()}

        # 3. Закрытые за неделю (throughput)
        cur.execute("""
            SELECT
                CASE
                    WHEN GROUP_ID IN (328) THEN 'WEB'
                    WHEN GROUP_ID IN (342) THEN '1С'
                    WHEN GROUP_ID IN (527, 353) THEN 'ПРОИЗВОДСТВО'
                    WHEN GROUP_ID = 102 THEN 'ТП'
                    ELSE 'ДРУГОЕ'
                END as grp,
                COUNT(*) as cnt
            FROM b_tasks
            WHERE GROUP_ID IN (328, 342, 527, 353, 102)
            AND STATUS = 5
            AND CLOSED_DATE >= %s
            GROUP BY grp
        """, [week_ago])
        data['closed_week'] = {r['grp']: r['cnt'] for r in cur.fetchall()}

        # 4. Часы списания за неделю по группам
        cur.execute("""
            SELECT
                CASE
                    WHEN t.GROUP_ID IN (328) THEN 'WEB'
                    WHEN t.GROUP_ID IN (342) THEN '1С'
                    WHEN t.GROUP_ID IN (527, 353) THEN 'ПРОИЗВОДСТВО'
                    WHEN t.GROUP_ID = 102 THEN 'ТП'
                    ELSE 'ДРУГОЕ'
                END as grp,
                ROUND(SUM(e.MINUTES) / 60, 1) as hours
            FROM b_tasks_elapsed_time e
            JOIN b_tasks t ON t.ID = e.TASK_ID
            WHERE t.GROUP_ID IN (328, 342, 527, 353, 102)
            AND e.CREATED_DATE >= %s
            GROUP BY grp
        """, [week_ago])
        data['hours_week'] = {r['grp']: float(r['hours'] or 0) for r in cur.fetchall()}

        # 5. Возвраты за неделю по группам
        cur.execute("""
            SELECT
                CASE
                    WHEN t.GROUP_ID IN (328) THEN 'WEB'
                    WHEN t.GROUP_ID IN (342) THEN '1С'
                    WHEN t.GROUP_ID IN (527, 353) THEN 'ПРОИЗВОДСТВО'
                    ELSE 'ДРУГОЕ'
                END as grp,
                COUNT(*) as cnt
            FROM b_tasks_log tl
            JOIN b_tasks t ON t.ID = tl.TASK_ID
            WHERE tl.FIELD = 'STAGE'
            AND tl.TO_VALUE IN ('Правки/Доработки', 'Возврат на доработку', 'На доработке')
            AND tl.CREATED_DATE >= %s
            AND t.GROUP_ID IN (328, 342, 527, 353)
            GROUP BY grp
        """, [week_ago])
        data['returns_week'] = {r['grp']: r['cnt'] for r in cur.fetchall()}

        # 6. ТП: нераспределённые заявки (STAGE_ID=0)
        cur.execute("""
            SELECT COUNT(*) as cnt,
                   SUM(CASE WHEN DATEDIFF(NOW(), CREATED_DATE) > 2 THEN 1 ELSE 0 END) as old_cnt,
                   MAX(DATEDIFF(NOW(), CREATED_DATE)) as max_days
            FROM b_tasks
            WHERE GROUP_ID = 102
            AND STATUS IN (1, 2, 3)
            AND STAGE_ID = 0
        """)
        r = cur.fetchone()
        data['tp_unassigned'] = {'total': r['cnt'], 'old': r['old_cnt'], 'max_days': r['max_days']}

        # 7. Долгие задачи (аномалии >30 дней в работе)
        cur.execute("""
            SELECT
                CASE
                    WHEN GROUP_ID IN (328) THEN 'WEB'
                    WHEN GROUP_ID IN (342) THEN '1С'
                    WHEN GROUP_ID IN (527, 353) THEN 'ПРОИЗВОДСТВО'
                    WHEN GROUP_ID = 102 THEN 'ТП'
                END as grp,
                COUNT(*) as cnt,
                MAX(DATEDIFF(NOW(), CREATED_DATE)) as max_days
            FROM b_tasks
            WHERE GROUP_ID IN (328, 342, 527, 353, 102)
            AND STATUS IN (1, 2, 3)
            AND DATEDIFF(NOW(), CREATED_DATE) > 30
            GROUP BY grp
        """)
        data['long_tasks'] = {r['grp']: {'cnt': r['cnt'], 'max_days': r['max_days']} for r in cur.fetchall()}

        # 8. Кол-во сотрудников по группам (для WIP per person)
        cur.execute("""
            SELECT
                CASE
                    WHEN t.GROUP_ID IN (328) THEN 'WEB'
                    WHEN t.GROUP_ID IN (342) THEN '1С'
                    WHEN t.GROUP_ID IN (527, 353) THEN 'ПРОИЗВОДСТВО'
                    WHEN t.GROUP_ID = 102 THEN 'ТП'
                END as grp,
                COUNT(DISTINCT t.RESPONSIBLE_ID) as people
            FROM b_tasks t
            WHERE t.GROUP_ID IN (328, 342, 527, 353, 102)
            AND t.STATUS IN (1, 2, 3)
            GROUP BY grp
        """)
        data['people_by_group'] = {r['grp']: r['people'] for r in cur.fetchall()}

    conn.close()
    return data


def format_data_for_llm(data: dict) -> str:
    """Форматирует собранные данные в читаемый текст для Claude."""
    week_ago, today = get_week_dates()
    groups = ['WEB', '1С', 'ПРОИЗВОДСТВО', 'ТП']

    lines = [f"Данные ИТ-отдела Markformelle за период {week_ago} — {today}\n"]

    lines.append("## ЗАДАЧИ В РАБОТЕ (WIP)")
    for g in groups:
        active = data['active_by_group'].get(g, 0)
        people = data['people_by_group'].get(g, 1)
        wip_per_person = round(active / people, 1) if people else 0
        lines.append(f"  {g}: {active} задач, {people} чел., WIP/чел = {wip_per_person}")

    lines.append("\n## ПРОСРОЧКА")
    for g in groups:
        od = data['overdue_by_group'].get(g, {})
        if od:
            lines.append(f"  {g}: >7дн={od.get('over_7',0)}, >30дн={od.get('over_30',0)}, >90дн={od.get('over_90',0)}")
        else:
            lines.append(f"  {g}: просрочки нет")

    lines.append("\n## ЗАКРЫТО ЗА НЕДЕЛЮ (Throughput)")
    for g in groups:
        lines.append(f"  {g}: {data['closed_week'].get(g, 0)} задач")

    lines.append("\n## СПИСАНО ЧАСОВ ЗА НЕДЕЛЮ")
    for g in groups:
        lines.append(f"  {g}: {data['hours_week'].get(g, 0)} ч")

    lines.append("\n## ВОЗВРАТЫ НА ДОРАБОТКУ ЗА НЕДЕЛЮ")
    for g in ['WEB', '1С', 'ПРОИЗВОДСТВО']:
        lines.append(f"  {g}: {data['returns_week'].get(g, 0)} возвратов")

    lines.append("\n## ДОЛГИЕ ЗАДАЧИ (>30 дней в работе)")
    for g in groups:
        lt = data['long_tasks'].get(g, {})
        if lt:
            lines.append(f"  {g}: {lt['cnt']} задач, максимум {lt['max_days']} дней")
        else:
            lines.append(f"  {g}: нет")

    tp = data['tp_unassigned']
    lines.append(f"\n## ТП: НЕРАСПРЕДЕЛЁННЫЕ ЗАЯВКИ")
    lines.append(f"  Всего без исполнителя: {tp['total']}, из них висят >2 дней: {tp['old']}, максимум {tp['max_days']} дней")

    return '\n'.join(lines)


def call_claude(data_text: str) -> str:
    """Отправляет данные в Claude API и получает дайджест."""
    prompt = f"""Ты опытный ИТ-аналитик компании Markformelle (производитель одежды, Беларусь).
Тебе предоставлены данные из системы управления задачами Битрикс24 за прошедшую неделю.
Группы: WEB (веб-разработка), 1С (1С-разработка), ПРОИЗВОДСТВО (производственные системы), ТП (техподдержка).

Напиши еженедельный ИТ-дайджест для руководства. Структура:

📅 ИТ-Дайджест [период]

🔥 ГЛАВНЫЕ РИСКИ (требуют внимания руководства):
— Выдели 2-4 самых критичных проблемы с конкретными цифрами
— Укажи аномалии (WIP слишком высокий, просрочка растёт, низкий throughput)

✅ УСПЕХИ НЕДЕЛИ:
— Что идёт хорошо, где есть прогресс

📊 СВОДКА ПО ГРУППАМ:
— Краткая таблица: группа | в работе | закрыто | просрочка | часы
— WIP/чел норма: до 5 задач на человека

💡 РЕКОМЕНДАЦИИ:
— 2-3 конкретных действия для улучшения ситуации

Пиши на русском, деловым языком, кратко и ёмко. Максимум 800 слов.
Не придумывай данные которых нет — используй только то что предоставлено.

ДАННЫЕ:
{data_text}"""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}]
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()['content'][0]['text']


def send_telegram(chat_id: str, text: str):
    """Отправляет сообщение в Telegram (разбивает если >4000 символов)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }, proxies={"http": None, "https": None})
        if not r.ok:
            print(f"Telegram error: {r.text}")


def send_bitrix_chat(chat_id: str, text: str):
    """Отправляет сообщение в групповой чат Bitrix24."""
    if not chat_id or not BITRIX_WEBHOOK_URL:
        return
    # Убираем markdown — Bitrix не поддерживает
    clean = text.replace('**', '').replace('*', '').replace('_', '').replace('`', '')
    requests.post(
        f"{BITRIX_WEBHOOK_URL}im.message.add.json",
        json={"DIALOG_ID": chat_id, "MESSAGE": clean},
        proxies={"http": None, "https": None},
        timeout=30,
    )


def run_digest():
    print(f"[{datetime.now()}] Запуск дайджеста...")
    try:
        data = collect_data()
        print("Данные собраны.")
        data_text = format_data_for_llm(data)
        print("Данные отформатированы, отправляем в Claude...")
        digest_text = call_claude(data_text)
        print("Дайджест получен от Claude.")

        # Отправляем в Telegram
        send_telegram(DIGEST_TELEGRAM_CHAT_ID, digest_text)
        print(f"Отправлено в Telegram ({DIGEST_TELEGRAM_CHAT_ID})")

        # Дублируем в Bitrix24
        if DIGEST_BITRIX_CHAT_ID:
            send_bitrix_chat(DIGEST_BITRIX_CHAT_ID, digest_text)
            print(f"Дублировано в Bitrix24 чат ({DIGEST_BITRIX_CHAT_ID})")

        print("Дайджест успешно отправлен!")
    except Exception as e:
        print(f"Ошибка дайджеста: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_digest()
