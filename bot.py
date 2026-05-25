"""
Telegram-бот для работы с Битрикс24
Команды:
  /start      — приветствие
  /tasks      — список задач по группам (WEB / 1С / ПРОИЗВОДСТВО / Все)
  /calendar   — встречи на сегодня и неделю
  /add_meeting — создать встречу в календаре
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)
from bitrix import get_my_tasks, get_calendar_events, create_meeting
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
    "5": "⚠️ Просрочена",
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
    """Показать кнопки выбора группы."""
    keyboard = [
        [
            InlineKeyboardButton("🌐 WEB", callback_data="tasks_WEB"),
            InlineKeyboardButton("💼 1С", callback_data="tasks_1С"),
        ],
        [
            InlineKeyboardButton("🏭 ПРОИЗВОДСТВО", callback_data="tasks_ПРОИЗВОДСТВО"),
            InlineKeyboardButton("📋 Все", callback_data="tasks_ALL"),
        ],
    ]
    await update.message.reply_text(
        "Выбери группу задач:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def tasks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Загрузить и показать задачи выбранной группы."""
    query = update.callback_query
    await query.answer()

    group = query.data.replace("tasks_", "")
    group_label = group if group != "ALL" else "все группы"

    await query.edit_message_text(f"⏳ Загружаю задачи ({group_label})...")

    result = get_my_tasks(group=group)

    if not result["success"]:
        await query.edit_message_text(f"❌ Ошибка: {result['error']}")
        return

    task_list = result["tasks"]

    if not task_list:
        await query.edit_message_text(f"📭 Задач в группе «{group_label}» нет.")
        return

    lines = [f"📋 *Задачи — {group_label} ({len(task_list)}):*\n"]
    for t in task_list:
        status = STATUS_LABELS.get(str(t.get("status", "1")), "❓")
        title = t.get("title", "Без названия")
        deadline = t.get("deadline", "")
        deadline_str = f"\n   ⏰ {deadline[:10]}" if deadline else ""
        lines.append(f"• *{title}*\n   {status}{deadline_str}\n")

    # Telegram ограничивает сообщения до 4096 символов
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n\n_...список обрезан, показаны первые задачи_"

    await query.edit_message_text(text, parse_mode="Markdown")


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
    await update.message.reply_text(
        "Шаг 2/4: Введи *дату* (ДД.ММ.ГГГГ):", parse_mode="Markdown"
    )
    return DATE


async def add_meeting_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["date"] = update.message.text
    await update.message.reply_text(
        "Шаг 3/4: Введи *время начала* (ЧЧ:ММ):", parse_mode="Markdown"
    )
    return TIME


async def add_meeting_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["time"] = update.message.text
    await update.message.reply_text(
        "Шаг 4/4: Введи *продолжительность* в минутах:", parse_mode="Markdown"
    )
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
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

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
    app.add_handler(CallbackQueryHandler(tasks_callback, pattern="^tasks_"))
    app.add_handler(CallbackQueryHandler(calendar_callback, pattern="^cal_"))
    app.add_handler(meeting_handler)

    print("🤖 Бот запущен! Нажми Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
