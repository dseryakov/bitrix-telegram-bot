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
os.environ["NO_PROXY"] = "*"

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)

from bitrix import get_tasks, get_calendar_events, create_meeting, get_last_comment, find_user_by_email, send_verification_code
from config import TELEGRAM_TOKEN
from users import get_bitrix_user, register_user
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
from analytics import quick_analytics, full_analytics

TITLE, DATE, TIME, DURATION = range(4)
REGISTER_EMAIL = 10
REGISTER_CODE = 11

STATUS_LABELS = {
    "1": "🆕 Новая",
    "2": "⏳ В работе",
    "3": "⏸ Ждёт контроля",
    "4": "✅ Завершена",
    "5": "🔴 Просрочена",
    "6": "🔄 Отложена",
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = get_bitrix_user(telegram_id)
    if user:
        text = (
            f"👋 Привет, {user['name']}!\n\n"
            "📋 /tasks — задачи по группам\n"
            "📅 /calendar — встречи\n"
            "➕ /add_meeting — создать встречу\n"
        )
        await update.message.reply_text(text)
    else:
        await update.message.reply_text(
            "👋 Привет! Для начала нужно привязать твой аккаунт Битрикс24.\n\n"
            "Введи свой корпоративный email:"
        )
        return REGISTER_EMAIL
    
async def register_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    await update.message.reply_text("⏳ Ищу тебя в Битрикс24...")

    result = find_user_by_email(email)

    if not result["success"]:
        await update.message.reply_text(
            "❌ Пользователь с таким email не найден.\n"
            "Попробуй ещё раз или обратись к администратору."
        )
        return REGISTER_EMAIL

    # Генерируем код
    import random
    code = str(random.randint(100000, 999999))

    # Сохраняем данные пользователя временно
    context.user_data["bitrix_id"] = result["id"]
    context.user_data["bitrix_name"] = result["name"]

    # Отправляем код в Битрикс24
    from users import save_code
    save_code(update.effective_user.id, code)
    send_result = send_verification_code(result["id"], code)

    if not send_result["success"]:
        await update.message.reply_text(f"❌ Не удалось отправить код: {send_result['error']}")
        return REGISTER_EMAIL

    await update.message.reply_text(
        f"📨 Код отправлен в твой чат Битрикс24!\n\n"
        f"Введи 6-значный код из сообщения от Информатора:"
    )
    return REGISTER_CODE


async def register_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    from users import verify_code
    
    if not verify_code(update.effective_user.id, code):
        await update.message.reply_text(
            "❌ Неверный или истёкший код. Попробуй ещё раз\n"
            "или напиши /start чтобы начать заново."
        )
        return REGISTER_CODE

    # Регистрируем пользователя
    bitrix_id = context.user_data["bitrix_id"]
    bitrix_name = context.user_data["bitrix_name"]
    register_user(update.effective_user.id, bitrix_id, bitrix_name)

    await update.message.reply_text(
        f"✅ Отлично, {bitrix_name}! Доступ открыт.\n\n"
        "📋 /tasks — задачи по группам\n"
        "📅 /calendar — встречи\n"
        "➕ /add_meeting — создать встречу\n"
    )
    return ConversationHandler.END

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

    bitrix_user = get_bitrix_user(query.from_user.id)
    user_id = bitrix_user["bitrix_id"] if bitrix_user else "72721"
    result = get_tasks(group=group, filter_type=filter_type, user_id=user_id)

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
        deadline_str = f"\n   ⏰ Дедлайн: {deadline[:10]}" if deadline else "\n   ⏰ Дедлайн: не указан"
        responsible_id = t.get("responsibleId", "")
        responsible_name = t.get("responsible", {}).get("name", "Не указан") if isinstance(t.get("responsible"), dict) else "Не указан"
        time_spent = int(t.get("timeSpentInLogs", 0) or 0)
        hours = time_spent // 3600
        minutes = (time_spent % 3600) // 60
        time_str = f"\n   ⏱ Списано: {hours}ч {minutes}мин"
        task_id = t.get("id", "")
        task_url = f"https://mfportal.by/company/personal/user/0/tasks/task/view/{task_id}/"
        last_comment = get_last_comment(task_id)
        comment_str = f"\n   💬 {last_comment}" if last_comment else ""
        lines.append(f"• *{title}*\n   {status}\n   👤 {responsible_name}{deadline_str}{time_str}{comment_str}\n   [Ссылка]({task_url})\n")

    # Статистика по ответственным
    stats = {}
    for t in task_list:
        name = t.get("responsible", {}).get("name", "Не указан") if isinstance(t.get("responsible"), dict) else "Не указан"
        stats[name] = stats.get(name, 0) + 1
    
    stats_lines = ["\n\n📊 *Задач по специалистам:*"]
    for name, count in sorted(stats.items(), key=lambda x: -x[1]):
        stats_lines.append(f"   👤 {name}: *{count}*")
    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n\n_...показаны первые задачи_"
    text = text + "\n".join(stats_lines)

    keyboard = [[InlineKeyboardButton("🔄 Выбрать другую группу", callback_data="back_to_groups")]]
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.edit_message_text(text.replace("*", "").replace("_", ""), reply_markup=InlineKeyboardMarkup(keyboard))


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

    bitrix_user = get_bitrix_user(query.from_user.id)
    user_id = bitrix_user["bitrix_id"] if bitrix_user else "72721"
    result = get_calendar_events(period=period, user_id=user_id)

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

    bitrix_user = get_bitrix_user(update.effective_user.id)
    user_id = bitrix_user["bitrix_id"] if bitrix_user else "72721"
    result = create_meeting(
    title=data["title"],
    date=data["date"],
    time=data["time"],
    duration_minutes=int(data["duration"]),
    user_id=user_id,
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
async def back_to_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
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
    await query.edit_message_text("Выбери группу задач:", reply_markup=InlineKeyboardMarkup(keyboard))
async def analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🌐 WEB", callback_data="anal_WEB"),
            InlineKeyboardButton("💼 1С", callback_data="anal_1С"),
        ],
        [
            InlineKeyboardButton("🏭 ПРОИЗВОДСТВО", callback_data="anal_ПРОИЗВОДСТВО"),
            InlineKeyboardButton("📋 Все", callback_data="anal_ALL"),
        ],
    ]
    await update.message.reply_text("📊 Аналитика — выбери группу:", reply_markup=InlineKeyboardMarkup(keyboard))


async def analytics_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group = query.data.replace("anal_", "")
    context.user_data["anal_group"] = group
    group_label = group if group != "ALL" else "Все группы"
    keyboard = [[
        InlineKeyboardButton("⚡ Быстрый (50 задач)", callback_data="anal_type_quick"),
        InlineKeyboardButton("🔍 Полный (за год)", callback_data="anal_type_full"),
    ]]
    await query.edit_message_text(
        f"Группа: *{group_label}*\nВыбери тип анализа:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def resetall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from users import save_users
    save_users({})
    await update.message.reply_text("✅ Все пользователи сброшены. Напиши /start для повторной авторизации.")

def format_days(days):
    if days is None:
        return "—"
    days = int(days)
    if days < 7:
        return f"{days} дн."
    elif days < 30:
        weeks = days // 7
        remainder = days % 7
        if remainder:
            return f"{weeks} нед. {remainder} дн."
        return f"{weeks} нед."
    elif days < 365:
        months = days // 30
        remainder = days % 30
        if remainder:
            return f"{months} мес. {remainder} дн."
        return f"{months} мес."
    else:
        years = days // 365
        remainder = days % 365
        if remainder:
            months = remainder // 30
            return f"{years} г. {months} мес." if months else f"{years} г."
        return f"{years} г."

async def analytics_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    anal_type = query.data.replace("anal_type_", "")
    group = context.user_data.get("anal_group", "ALL")
    group_label = group if group != "ALL" else "Все группы"
    type_label = "⚡ Быстрый" if anal_type == "quick" else "🔍 Полный"

    await query.edit_message_text(f"⏳ Считаю аналитику для {group_label}...")

    result = quick_analytics(group) if anal_type == "quick" else full_analytics(group)

    if not result["success"]:
        await query.edit_message_text(f"❌ Ошибка: {result.get('error')}")
        return

    a = result["analyst"]
    t = result["tester"]
    analyzed = result.get("analyzed") or result.get("total_closed", 0)

    def conclusion(a_or_t, role_name):
        wc = a_or_t["with_count"]
        woc = a_or_t["without_count"]
        w_avg = a_or_t["with_avg_days"]
        wo_avg = a_or_t["without_avg_days"]
        diff = a_or_t["faster_pct"]

        if wc == 0:
            return f"📭 Задач с {role_name} не найдено в выборке"
        if woc == 0:
            return f"📌 Все задачи выборки с {role_name}"

        if diff > 10:
            verdict = (
                f"✅ *Вывод:* с {role_name} задачи закрываются быстрее на {diff}%\n"
                f"   ({format_days(w_avg)} vs {format_days(wo_avg)}) — {role_name} ускоряет процесс"
            )
        elif diff < -10:
            verdict = (
                f"📌 *Вывод:* задачи с {role_name} сложнее и дольше на {abs(diff)}%\n"
                f"   ({format_days(w_avg)} vs {format_days(wo_avg)})\n"
                f"   💡 Это норма — {role_name} берётся за нетривиальные задачи.\n"
                f"   Важнее смотреть на % возвратов и качество сдачи."
            )
        else:
            verdict = (
                f"➡️ *Вывод:* {role_name} не влияет на скорость закрытия\n"
                f"   ({format_days(w_avg)} vs {format_days(wo_avg)}) — разница несущественна"
            )

        return verdict

    return_line = f"🔄 Сейчас в стадии возврата: *{result['return_now']}* задач\n"
    if result.get("total_returns"):
        return_line += f"📊 За год возвращалось: *{result['total_returns']}* задач (*{result['total_return_events']}* раз)\n"

    text = (
        f"📊 *Аналитика {group_label}* — {type_label}\n"
        f"Проанализировано: *{analyzed}* из {result['total_closed']} закрытых задач за год\n"
        f"_(avg = среднее время от создания до закрытия)_\n\n"
        f"*👨‍💼 Роль аналитика:*\n"
        f"• С аналитиком: {a['with_count']} задач — avg *{format_days(a['with_avg_days'])}*\n"
        f"• Без аналитика: {a['without_count']} задач — avg *{format_days(a['without_avg_days'])}*\n"
        f"{conclusion(a, 'аналитиком')}\n\n"
        f"*🧪 Роль тестировщика:*\n"
        f"• С тестировщиком: {t['with_count']} задач — avg *{format_days(t['with_avg_days'])}*\n"
        f"• Без тестировщика: {t['without_count']} задач — avg *{format_days(t['without_avg_days'])}*\n"
        f"{conclusion(t, 'тестировщиком')}\n\n"
        f"{return_line}"
    )

    # Блок по аналитикам
    if a.get("by_person"):
        text += "\n*👤 Аналитики:*\n"
        for name, stat in list(a["by_person"].items())[:5]:
            roles_str = []
            if stat["responsible"]: roles_str.append(f"исполнитель: {stat['responsible']}")
            if stat["accomplice"]: roles_str.append(f"соисполнитель: {stat['accomplice']}")
            if stat["auditor"]: roles_str.append(f"наблюдатель: {stat['auditor']}")
            returns_str = f", возвратов: {stat['returns']} в {stat['tasks_with_returns']} задачах" if stat['returns'] else ""
            text += f"   *{name}*: {stat['count']} задач, avg {format_days(stat['avg_days'])}{returns_str}\n"
            text += f"   _{', '.join(roles_str)}_\n"

    if t.get("by_person"):
        text += "\n*🧪 Тестировщики:*\n"
        for name, stat in list(t["by_person"].items())[:5]:
            roles_str = []
            if stat["responsible"]: roles_str.append(f"исполнитель: {stat['responsible']}")
            if stat["accomplice"]: roles_str.append(f"соисполнитель: {stat['accomplice']}")
            if stat["auditor"]: roles_str.append(f"наблюдатель: {stat['auditor']}")
            returns_str = f", возвратов: {stat['returns']} в {stat['tasks_with_returns']} задачах" if stat['returns'] else ""
            text += f"   *{name}*: {stat['count']} задач, avg {format_days(stat['avg_days'])}{returns_str}\n"
            text += f"   _{', '.join(roles_str)}_\n"

    keyboard = [
        [InlineKeyboardButton("🔄 Возвраты по специалистам", callback_data=f"anal_returns_{group}")],
        [InlineKeyboardButton("🔙 Выбрать другую группу", callback_data="anal_back")],
    ]
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.edit_message_text(text.replace("*", ""), reply_markup=InlineKeyboardMarkup(keyboard))

async def analytics_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [
            InlineKeyboardButton("🌐 WEB", callback_data="anal_WEB"),
            InlineKeyboardButton("💼 1С", callback_data="anal_1С"),
        ],
        [
            InlineKeyboardButton("🏭 ПРОИЗВОДСТВО", callback_data="anal_ПРОИЗВОДСТВО"),
            InlineKeyboardButton("📋 Все", callback_data="anal_ALL"),
        ],
    ]
    await query.edit_message_text("📊 Аналитика — выбери группу:", reply_markup=InlineKeyboardMarkup(keyboard))  

async def analytics_returns_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group = query.data.replace("anal_returns_", "")
    group_label = group if group != "ALL" else "Все группы"

    await query.edit_message_text(f"⏳ Считаю возвраты для {group_label}...")

    from analytics import return_analytics
    result = return_analytics(group)

    text = (
        f"🔄 *Возвраты на доработку — {group_label}*\n"
        f"Всего задач в стадии возврата: *{result['total_return']}*\n"
        f"Без аналитика и тестировщика: *{result['no_specialist']}*\n\n"
    )

    if result["analyst_returns"]:
        text += "*👨‍💼 Аналитики в возвращённых задачах:*\n"
        for name, count in list(result["analyst_returns"].items())[:7]:
            text += f"   {name}: *{count}* задач\n"
        text += "\n"

    if result["tester_returns"]:
        text += "*🧪 Тестировщики в возвращённых задачах:*\n"
        for name, count in list(result["tester_returns"].items())[:7]:
            text += f"   {name}: *{count}* задач\n"

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="anal_back")]]
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.edit_message_text(text.replace("*", ""), reply_markup=InlineKeyboardMarkup(keyboard))      
def main():
    import httpx
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(proxy=None)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).request(request).build()
    from telegram import BotCommand
    async def set_commands(app):
        await app.bot.set_my_commands([
            BotCommand("tasks", "Задачи по группам"),
            BotCommand("calendar", "Встречи"),
            BotCommand("analytics", "Аналитика задач"),
            BotCommand("add_meeting", "Создать встречу"),
        ])
    async def on_startup(app):
        from analytics import load_user_cache
        from telegram import BotCommand
        print("⏳ Загружаю кэш пользователей...")
        load_user_cache()
        print("✅ Кэш загружен")
        await app.bot.set_my_commands([
            BotCommand("tasks", "Задачи по группам"),
            BotCommand("calendar", "Встречи"),
            BotCommand("add_meeting", "Создать встречу"),
            BotCommand("analytics", "Аналитика задач"),
        ])
    
    app.post_init = on_startup
    app.post_init = set_commands
    register_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        REGISTER_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_email)],
        REGISTER_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_code)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(register_handler)
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

    app.add_handler(CommandHandler("tasks", tasks))
    app.add_handler(CommandHandler("calendar", calendar))
    app.add_handler(CallbackQueryHandler(group_callback, pattern="^group_"))
    app.add_handler(CallbackQueryHandler(filter_callback, pattern="^filter_"))
    app.add_handler(CallbackQueryHandler(back_to_groups, pattern="^back_to_groups$"))
    app.add_handler(CallbackQueryHandler(calendar_callback, pattern="^cal_"))
    app.add_handler(meeting_handler)
    app.add_handler(CommandHandler("analytics", analytics))
    app.add_handler(CallbackQueryHandler(analytics_group_callback, pattern="^anal_(?!type_|back)"))
    app.add_handler(CallbackQueryHandler(analytics_type_callback, pattern="^anal_type_"))
    app.add_handler(CallbackQueryHandler(analytics_back_callback, pattern="^anal_back$"))
    app.add_handler(CommandHandler("resetall", resetall))
    app.add_handler(CallbackQueryHandler(analytics_returns_callback, pattern="^anal_returns_"))

    print("🤖 Бот запущен! Нажми Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
