"""
Автоматическая отправка недельной динамики по крону (вторник 09:15).
Отправляет тот же отчёт что и /weekly, но без кнопок.
"""
import os
import requests
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DIGEST_TELEGRAM_CHAT_ID = os.getenv("DIGEST_TELEGRAM_CHAT_ID", "780994722")


def send_telegram(chat_id: str, text: str):
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
            requests.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }, proxies={"http": None, "https": None}, timeout=15)


def get_weekly_data(gids, tp_filter_ids, days):
    from datetime import datetime
    from db import get_connection
    today = date.today()
    period_start = today - timedelta(days=days)
    prev_start = today - timedelta(days=days * 2)
    ph = ','.join(['%s'] * len(gids))
    tf = f" AND RESPONSIBLE_ID IN ({tp_filter_ids})" if tp_filter_ids else ""
    tf_t = f" AND t.RESPONSIBLE_ID IN ({tp_filter_ids})" if tp_filter_ids else ""
    conn = get_connection()
    r = {}
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) as cnt FROM b_tasks WHERE GROUP_ID IN ({ph}) AND CREATED_DATE >= %s{tf}", gids + [period_start])
        r['new_tasks'] = cur.fetchone()['cnt']
        cur.execute(f"SELECT COUNT(*) as cnt FROM b_tasks WHERE GROUP_ID IN ({ph}) AND STATUS IN (1,2,3){tf}", gids)
        r['active_now'] = cur.fetchone()['cnt']
        cur.execute(f"SELECT COUNT(*) as cnt FROM b_tasks WHERE GROUP_ID IN ({ph}) AND STATUS IN (1,2,3) AND CREATED_DATE < %s{tf}", gids + [period_start])
        r['active_prev'] = cur.fetchone()['cnt']
        cur.execute(f"SELECT COUNT(DISTINCT RESPONSIBLE_ID) as p FROM b_tasks WHERE GROUP_ID IN ({ph}) AND STATUS IN (1,2,3){tf}", gids)
        r['people'] = max(cur.fetchone()['p'] or 1, 1)
        cur.execute(f"""SELECT COUNT(*) as cnt FROM b_tasks WHERE GROUP_ID IN ({ph}) AND STATUS IN (1,2,3)
            AND DEADLINE IS NOT NULL AND DEADLINE < NOW() AND DATEDIFF(NOW(), CREATED_DATE) > 90{tf}""", gids)
        r['overdue_90'] = cur.fetchone()['cnt']
        cur.execute(f"SELECT COUNT(*) as cnt FROM b_tasks WHERE GROUP_ID IN ({ph}) AND STATUS=5 AND CLOSED_DATE >= %s{tf}", gids + [period_start])
        r['closed'] = cur.fetchone()['cnt']
        cur.execute(f"SELECT COUNT(*) as cnt FROM b_tasks WHERE GROUP_ID IN ({ph}) AND STATUS=5 AND CLOSED_DATE >= %s AND CLOSED_DATE < %s{tf}", gids + [prev_start, period_start])
        r['closed_prev'] = cur.fetchone()['cnt']
        cur.execute(f"""SELECT COALESCE(ROUND(SUM(e.MINUTES)/60.0,1),0) as hrs
            FROM b_tasks_elapsed_time e JOIN b_tasks t ON t.ID=e.TASK_ID
            WHERE t.GROUP_ID IN ({ph}) AND e.CREATED_DATE >= %s{tf_t}""", gids + [period_start])
        r['hours'] = float(cur.fetchone()['hrs'] or 0)
        cur.execute(f"""SELECT COUNT(*) as cnt FROM b_tasks_log tl JOIN b_tasks t ON t.ID=tl.TASK_ID
            WHERE tl.FIELD='STAGE' AND tl.TO_VALUE IN ('Правки/Доработки','Возврат на доработку','На доработке')
            AND tl.CREATED_DATE >= %s AND t.GROUP_ID IN ({ph})""", [period_start] + gids)
        r['returns'] = cur.fetchone()['cnt']
    conn.close()
    return r


def health_signal(wip, overdue_90, throughput, returns):
    score = 0
    flags = []
    if wip > 10:
        score += 3; flags.append(f"задач/чел {wip} >> нормы")
    elif wip > 5:
        score += 1; flags.append(f"задач/чел {wip} > нормы")
    if overdue_90 > 10:
        score += 2; flags.append(f"просрочка >90д: {overdue_90}")
    elif overdue_90 > 5:
        score += 1
    if throughput < 5:
        score += 2; flags.append(f"низкая скорость закрытия: {throughput}")
    elif throughput < 10:
        score += 1
    if returns > 5:
        score += 1; flags.append(f"возвраты: {returns}")
    if score == 0: return "🟢", flags
    elif score <= 3: return "🟡", flags
    else: return "🔴", flags


def run_weekly_send():
    from db import TP_RETAIL, TP_SYSADMIN, TP_SYSADMIN_UZ
    tp_all = TP_RETAIL + TP_SYSADMIN + TP_SYSADMIN_UZ
    tp_str = ','.join(map(str, tp_all))

    days = 7
    today = date.today()
    period_start = today - timedelta(days=days)

    GROUPS = [
        ("🌐 WEB", [328], None),
        ("💼 1С", [342], None),
        ("🏭 ПРОИЗВ.", [527, 353], None),
        ("🛠 ТП", [102], tp_str),
    ]

    lines = [f"📊 *Динамика за неделю* ({period_start.strftime('%d.%m')} — {today.strftime('%d.%m.%Y')})\n"]
    group_signals = []

    for grp_label, gids, tp_filter_ids in GROUPS:
        d = get_weekly_data(gids, tp_filter_ids, days)
        wip = round(d['active_now'] / d['people'], 1)
        hrs_per = round(d['hours'] / d['people'], 1)
        delta = d['active_now'] - d['active_prev']
        delta_str = f"↑+{delta}" if delta > 0 else (f"↓{delta}" if delta < 0 else "→")
        t_delta = d['closed'] - d['closed_prev']
        t_str = f"↑+{t_delta}" if t_delta > 0 else (f"↓{t_delta}" if t_delta < 0 else "→")
        signal, flags = health_signal(wip, d['overdue_90'], d['closed'], d['returns'])
        group_signals.append(signal)

        wip_s = "🔴" if wip > 10 else ("🟡" if wip > 5 else "🟢")
        active_s = "🔴" if delta > 10 else ("🟡" if delta > 0 else "🟢")
        closed_s = "🟢" if t_delta > 0 else ("🟡" if t_delta == 0 else "🔴")
        overdue_s = "🔴" if d['overdue_90'] > 10 else ("🟡" if d['overdue_90'] > 5 else "🟢")

        lines.append(f"{signal} {grp_label} — {today.strftime('%d.%m.%Y')}")
        lines.append(f"В работе: *{d['active_now']}* ({delta_str}) | Закрыто: *{d['closed']}* ({t_str}) | Задач/чел: *{wip}*")
        lines.append("")
        lines.append("📊 *Детали:*")
        lines.append(f"{active_s} Очередь задач: {d['active_now']} ({delta_str} за неделю)")
        lines.append(f"{closed_s} Скорость закрытия: {d['closed']} задач ({t_str})")
        lines.append(f"{overdue_s} Просрочка >90 дней: {d['overdue_90']}")
        lines.append(f"{wip_s} Задач на сотрудника: {wip} (норма 5)")
        lines.append(f"💊 Оценка: {signal}")
        if flags:
            lines.append(f"⚠️ _{', '.join(flags)}_")
        lines.append("")

    red = sum(1 for s in group_signals if s == "🔴")
    yellow = sum(1 for s in group_signals if s == "🟡")
    if red >= 2: overall = "🔴 Критично"
    elif red == 1 or yellow >= 2: overall = "🟡 Требует внимания"
    else: overall = "🟢 Хорошо"
    lines.append(f"💊 *Здоровье команды: {overall}*")

    text = "\n".join(lines)
    send_telegram(DIGEST_TELEGRAM_CHAT_ID, text)
    print(f"[{date.today()}] Weekly отправлен в {DIGEST_TELEGRAM_CHAT_ID}")


if __name__ == "__main__":
    run_weekly_send()
