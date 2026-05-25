"""
Telegram-бот для работы с Битрикс24
/start      — приветствие
/tasks      — задачи по группам → важные / важные просроченные
/calendar   — встречи на сегодня и неделю
/add_meeting — создать встречу
"""
import os
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("ALL_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("all_proxy", None)

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)
from bitrix import get_tasks, get_calendar_events, create_meeting
from config import TELEGRAM_TOKEN

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TITLE, DATE, TIME, DURATION = range(4)

STATUS_LABELS = {
    "1": "🆕 Новая",
    "2": "⏳ В работе",
    "3": "⏸ Ждёт контроля",
    "4": "✅ Завершена",
    "5": "🔴 Просрочена",
    "6": "🔄 Отложена",
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Привет! Я твой помощник по Битрикс24.\n\n"
        "📋 /tasks — задачи по группам\n"
        "📅 /calendar — встречи\n"
        "➕ /add_meeting — создать встречу\n"
    )
    await update.message.reply_text(text)


async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 1 — выбор группы."""
    keyboard = [
        [
            InlineKeyboardButton("🌐 WEB", callback_data="group_WEB"),
            InlineKeyboardButton("💼 1С", callback_data="group_1С"),
        ],
        [
            InlineKeyboardButton("🏭 ПРОИЗВОДСТВО", callback_data="group_ПРОИЗВОДСТВО"),
            InlineKeyboardButton("📋 Все", callback_data="group_ALL"),
        ],
    ]
    await update.message.reply_text(
        "Шаг 1: Выбери группу задач:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2 — выбор типа фильтра после выбора группы."""
    query = update.callback_query
    await query.answer()

    group = query.data.replace("group_", "")
    context.user_data["group"] = group

    group_label = group if group != "ALL" else "Все группы"

    keyboard = [
        [
            InlineKeyboardButton("🔥 Важные", callback_data="filter_important"),
            InlineKeyboardButton("🔴 Важные просроченные", callback_data="filter_overdue"),
        ],
    ]
    await query.edit_message_text(
        f"Группа: *{group_label}*\nШаг 2: Выбери тип задач:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 3 — загрузить и показать задачи."""
    query = update.callback_query
    await query.answer()

    filter_type = query.data.replace("filter_", "")
    group = context.user_data.get("group", "ALL")

    group_label = group if group != "ALL" else "Все группы"
    filter_label = "🔥 Важные" if filter_type == "important" else "🔴 Важные просроченные"

    await query.edit_message_text(f"⏳ Загружаю задачи...")

    result = get_tasks(group=group, filter_type=filter_type)

    if not result["success"]:
        await query.edit_message_text(f"❌ Ошибка: {result['error']}")
        return

    task_list = result["tasks"]

    if not task_list:
        await query.edit_message_text(
            f"📭 Нет задач\nГруппа: {group_label} | {filter_label}"
        )
        return

    lines = [f"{filter_label} — *{group_label}* ({len(task_list)}):\n"]
    for t in task_list:
        status = STATUS_LABELS.get(str(t.get("status", "1")), "❓")
        title = t.get("title", "Без названия")
        deadline = t.get("deadline", "")
        deadline_str = f"\n   ⏰ {deadline[:10]}" if deadline else ""
        lines.append(f"• *{title}*\n   {status}{deadline_str}\n")

    text = "\n".join(lines)
    if len(text) > 4000:
        # Обрезаем аккуратно чтобы не сломать Markdown
        text = text[:3900] + "\n\n_...показаны первые задачи_"

    try:
        await query.edit_message_text(text, parse_mode="Markdown")
    except Exception:
        # Если Markdown сломан — отправляем без форматирования
        await query.edit_message_text(text.replace("*", "").replace("_", ""))


async def calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📅 Сегодня", callback_data="cal_today"),
            InlineKeyboardButton("📆 Неделя", callback_data="cal_week"),
        ]
    ]
    await update.message.reply_text(
        "Выбери период:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    period = "today" if query.data == "cal_today" else "week"
    period_text = "сегодня" if period == "today" else "эту неделю"

    await query.edit_message_text(f"⏳ Загружаю встречи на {period_text}...")

    result = get_calendar_events(period=period)

    if not result["success"]:
        await query.edit_message_text(f"❌ Ошибка: {result['error']}")
        return

    events = result["events"]
    if not events:
        await query.edit_message_text(f"📭 Встреч на {period_text} нет.")
        return

    lines = [f"📅 *Встречи на {period_text} ({len(events)}):*\n"]
    for e in events:
        name = e.get("name", "Без названия")
        date_from = e.get("date_from", "")[:16].replace("T", " ")
        date_to = e.get("date_to", "")[:16].replace("T", " ")
        lines.append(f"🗓 *{name}*\n   {date_from} → {date_to}\n")

    await query.edit_message_text("\n".join(lines), parse_mode="Markdown")


# ── Диалог создания встречи ──────────────────────────────────────────────────

async def add_meeting_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "➕ Создаём встречу!\n\nШаг 1/4: Введи *название*:",
        parse_mode="Markdown"
    )
    return TITLE


async def add_meeting_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["title"] = update.message.text
    await update.message.reply_text("Шаг 2/4: Введи *дату* (ДД.ММ.ГГГГ):", parse_mode="Markdown")
    return DATE


async def add_meeting_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["date"] = update.message.text
    await update.message.reply_text("Шаг 3/4: Введи *время начала* (ЧЧ:ММ):", parse_mode="Markdown")
    return TIME


async def add_meeting_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["time"] = update.message.text
    await update.message.reply_text("Шаг 4/4: Введи *продолжительность* в минутах:", parse_mode="Markdown")
    return DURATION


async def add_meeting_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["duration"] = update.message.text
    data = context.user_data
    await update.message.reply_text("⏳ Создаю встречу...")

    result = create_meeting(
        title=data["title"],
        date=data["date"],
        time=data["time"],
        duration_minutes=int(data["duration"]),
    )

    if result["success"]:
        await update.message.reply_text(
            f"✅ Встреча *{data['title']}* создана!\n"
            f"📅 {data['date']} в {data['time']}, {data['duration']} мин.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Ошибка: {result['error']}")

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END


# ── Запуск ───────────────────────────────────────────────────────────────────

def main():
    import httpx
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(proxy=None)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).request(request).build()

    meeting_handler = ConversationHandler(
        entry_points=[CommandHandler("add_meeting", add_meeting_start)],
        states={
            TITLE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meeting_title)],
            DATE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meeting_date)],
            TIME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meeting_time)],
            DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meeting_duration)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tasks", tasks))
    app.add_handler(CommandHandler("calendar", calendar))
    app.add_handler(CallbackQueryHandler(group_callback, pattern="^group_"))
    app.add_handler(CallbackQueryHandler(filter_callback, pattern="^filter_"))
    app.add_handler(CallbackQueryHandler(calendar_callback, pattern="^cal_"))
    app.add_handler(meeting_handler)

    print("🤖 Бот запущен! Нажми Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
