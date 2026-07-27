"""
Модуль для сохранения сообщений из Telegram чатов и генерации саммари.
"""
import os
import sqlite3
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TOGETHER_BASE_URL = os.getenv("TOGETHER_BASE_URL", "https://api.together.xyz/v1")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
DIGEST_TELEGRAM_CHAT_ID = os.getenv("DIGEST_TELEGRAM_CHAT_ID", "780994722")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_messages.db")

# Чаты для мониторинга
MONITORED_CHATS = {
    -1002822290717: "WEB",
    -1003824587590: "1С",
    -1004407869216: "Синван (1С)",
}


def save_message(chat_id: int, chat_title: str, user_id: int, user_name: str, text: str):
    """Сохраняет сообщение из чата в БД."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_messages (chat_id, chat_title, user_id, user_name, text) VALUES (?, ?, ?, ?, ?)",
        (chat_id, chat_title, user_id, user_name, text)
    )
    conn.commit()
    conn.close()


def get_messages(chat_id: int, since: datetime) -> list:
    """Получает сообщения из чата за период."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT user_name, text, created_at FROM chat_messages WHERE chat_id = ? AND created_at >= ? ORDER BY created_at ASC",
        (chat_id, since.strftime('%Y-%m-%d %H:%M:%S'))
    )
    rows = cur.fetchall()
    conn.close()
    return [{'user': r[0], 'text': r[1], 'time': r[2]} for r in rows]


def format_messages_for_llm(messages: list, chat_name: str, period: str) -> str:
    """Форматирует сообщения для отправки в LLM."""
    if not messages:
        return ""
    lines = [f"Переписка чата '{chat_name}' за {period}:\n"]
    for m in messages:
        time_short = m['time'][11:16] if len(m['time']) > 16 else m['time']
        lines.append(f"[{time_short}] {m['user']}: {m['text']}")
    return "\n".join(lines)


def call_llm(prompt: str) -> str:
    """Вызывает LLM для генерации саммари."""
    response = requests.post(
        TOGETHER_BASE_URL + "/chat/completions",
        headers={
            "Authorization": f"Bearer {TOGETHER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "meta-llama/llama-3.3-70b-instruct",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1500,
            "temperature": 0.5,
        },
        timeout=90,
    )
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content']


def send_telegram(chat_id: str, text: str):
    """Отправляет сообщение в Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        requests.post(url, json={
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }, proxies={"http": None, "https": None}, timeout=15)


def make_daily_summary():
    """Генерирует дневное саммари для всех мониторируемых чатов."""
    print(f"[{datetime.now()}] Генерация дневного саммари...")
    since = datetime.now() - timedelta(hours=24)
    period = datetime.now().strftime('%d.%m.%Y')

    summaries = []
    for chat_id, chat_name in MONITORED_CHATS.items():
        messages = get_messages(chat_id, since)
        if not messages:
            summaries.append(f"💬 *{chat_name}*: сообщений за день не было")
            continue

        print(f"  {chat_name}: {len(messages)} сообщений")
        text = format_messages_for_llm(messages, chat_name, period)
        prompt = f"""Ты аналитик ИТ-команды Markformelle. Прочитай переписку чата и сделай краткое саммари.

Структура:
📌 Что обсуждалось (2-4 пункта)
✅ Решения принятые за день
⚠️ Открытые вопросы / проблемы
👥 Кто был активен

Максимум 200 слов. На русском языке.

{text}"""
        try:
            summary = call_llm(prompt)
            summaries.append(f"💬 *{chat_name}* ({len(messages)} сообщ.):\n{summary}")
        except Exception as e:
            summaries.append(f"💬 *{chat_name}*: ошибка генерации саммари ({e})")

    result = f"📅 *Дневное саммари чатов* — {period}\n\n" + "\n\n---\n\n".join(summaries)
    send_telegram(DIGEST_TELEGRAM_CHAT_ID, result)
    print("Дневное саммари отправлено.")


def make_weekly_summary():
    """Генерирует недельное саммари для всех мониторируемых чатов."""
    print(f"[{datetime.now()}] Генерация недельного саммари...")
    since = datetime.now() - timedelta(days=7)
    week_start = since.strftime('%d.%m')
    week_end = datetime.now().strftime('%d.%m.%Y')
    period = f"{week_start}–{week_end}"

    summaries = []
    for chat_id, chat_name in MONITORED_CHATS.items():
        messages = get_messages(chat_id, since)
        if not messages:
            summaries.append(f"💬 *{chat_name}*: сообщений за неделю не было")
            continue

        print(f"  {chat_name}: {len(messages)} сообщений за неделю")
        # Для недельного берём каждое 3-е сообщение если их очень много
        if len(messages) > 200:
            messages = messages[::3]

        text = format_messages_for_llm(messages, chat_name, period)
        prompt = f"""Ты аналитик ИТ-команды Markformelle. Прочитай переписку чата за неделю и сделай саммари.

Структура:
📌 Главные темы недели (3-5 пунктов)
✅ Ключевые решения
⚠️ Нерешённые вопросы
📈 Динамика активности команды

Максимум 300 слов. На русском языке.

{text}"""
        try:
            summary = call_llm(prompt)
            summaries.append(f"💬 *{chat_name}* ({len(messages)} сообщ.):\n{summary}")
        except Exception as e:
            summaries.append(f"💬 *{chat_name}*: ошибка ({e})")

    result = f"📅 *Недельное саммари чатов* — {period}\n\n" + "\n\n---\n\n".join(summaries)
    send_telegram(DIGEST_TELEGRAM_CHAT_ID, result)
    print("Недельное саммари отправлено.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "weekly":
        make_weekly_summary()
    else:
        make_daily_summary()
