"""
Telegram-бот для работы с Битрикс24
Команды:
  /start      — приветствие
  /tasks      — список твоих задач с статусами
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

# Логирование — показывает ошибки в консоли
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Состояния для диалога создания встречи
TITLE, DATE, TIME, DURATION = range(4)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start — приветствие."""
    text = (
        "👋 Привет! Я твой помощник по Битрикс24.\n\n"
        "Что умею:\n"
        "📋 /tasks — показать твои задачи\n"
        "📅 /calendar — встречи на сегодня и эту неделю\n"
        "➕ /add_meeting — создать встречу\n"
    )
    await update.message.reply_text(text)


async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /tasks — получить задачи из Битрикс24."""
    await update.message.reply_text("⏳ Загружаю задачи...")

    result = get_my_tasks()

    if not result["success"]:
        await update.message.reply_text(f"❌ Ошибка: {result['error']}")
        return

    task_list = result["tasks"]

    if not task_list:
        await update.message.reply_text("✅ У тебя нет активных задач!")
        return

    # Иконки для статусов
    status_icons = {
        "1": "🆕 Новая",
        "2": "⏳ Выполняется",
        "3": "⏸ Ждёт контроля",
        "4": "✅ Завершена",
        "5": "⚠️ Просрочена",
        "6": "🔄 Отложена",
    }

    lines = [f"📋 *Твои задачи ({len(task_list)}):*\n"]
    for t in task_list:
        status = status_icons.get(str(t.get("status", "1")), "❓ Неизвестно")
        title = t.get("title", "Без названия")
        deadline = t.get("deadline", "")
        deadline_str = f"\n   ⏰ Дедлайн: {deadline[:10]}" if deadline else ""
        lines.append(f"• *{title}*\n   {status}{deadline_str}\n")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /calendar — встречи на сегодня и неделю."""
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
    """Обработка кнопок календаря."""
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
    """Начало диалога — запрашиваем название встречи."""
    await update.message.reply_text(
        "➕ Создаём встречу!\n\nШаг 1/4: Введи *название* встречи:",
        parse_mode="Markdown"
    )
    return TITLE


async def add_meeting_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["title"] = update.message.text
    await update.message.reply_text(
        "Шаг 2/4: Введи *дату* в формате ДД.ММ.ГГГГ\nНапример: 25.05.2025",
        parse_mode="Markdown"
    )
    return DATE


async def add_meeting_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["date"] = update.message.text
    await update.message.reply_text(
        "Шаг 3/4: Введи *время начала* в формате ЧЧ:ММ\nНапример: 14:30",
        parse_mode="Markdown"
    )
    return TIME


async def add_meeting_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["time"] = update.message.text
    await update.message.reply_text(
        "Шаг 4/4: Введи *продолжительность* в минутах\nНапример: 60",
        parse_mode="Markdown"
    )
    return DURATION


async def add_meeting_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["duration"] = update.message.text

    data = context.user_data
    await update.message.reply_text("⏳ Создаю встречу в Битрикс24...")

    result = create_meeting(
        title=data["title"],
        date=data["date"],
        time=data["time"],
        duration_minutes=int(data["duration"]),
    )

    if result["success"]:
        await update.message.reply_text(
            f"✅ Встреча *{data['title']}* создана!\n"
            f"📅 {data['date']} в {data['time']}, длительность {data['duration']} мин.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Ошибка: {result['error']}")

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена диалога."""
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END


# ── Запуск ───────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Диалог создания встречи
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
    app.add_handler(CallbackQueryHandler(calendar_callback, pattern="^cal_"))
    app.add_handler(meeting_handler)

    print("🤖 Бот запущен! Нажми Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
