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

from bitrix import get_tasks, get_calendar_events, create_meeting, get_last_comment, find_user_by_email, send_verification_code, get_task_tags
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
            "📊 /analytics — анализ по специалистам\n"
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
            InlineKeyboardButton("🛠 ТП", callback_data="group_ТП"),
        ],
        [
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
    """Шаг 3 — сводка по сотрудникам с кнопками."""
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

    # Обогащаем задачи тегами через Portal API
    task_ids = [t["id"] for t in task_list]
    tags_map = get_task_tags(task_ids)
    for t in task_list:
        t["tags"] = tags_map.get(str(t["id"]), [])

    # Сохраняем задачи и контекст для детального просмотра
    context.user_data["task_list"] = task_list
    context.user_data["filter_label"] = filter_label
    context.user_data["group_label"] = group_label
    context.user_data["filter_type"] = filter_type

    # Группируем по исполнителю
    by_responsible = {}
    for t in task_list:
        name = t.get("responsible_name", "Не указан")
        if name not in by_responsible:
            by_responsible[name] = {"tasks": [], "hours": 0}
        by_responsible[name]["tasks"].append(t)
        by_responsible[name]["hours"] += int(t.get("time_spent_seconds", 0) or 0)

    sorted_responsible = sorted(by_responsible.items(), key=lambda x: -len(x[1]["tasks"]))

    # Топ-теги по группе
    tag_counts = {}
    for t in task_list:
        for tag in t.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:5]

    # Строим сводку
    lines = [f"{filter_label} — *{group_label}* ({len(task_list)} задач):\n"]
    for name, data in sorted_responsible:
        count = len(data["tasks"])
        hours = data["hours"] // 3600
        minutes = (data["hours"] % 3600) // 60
        parts = name.split()
        short = f"{parts[-1]} {parts[0][0]}." if len(parts) >= 2 else name

        # Топ-3 тега сотрудника
        person_tag_counts = {}
        for t in data["tasks"]:
            for tag in t.get("tags", []):
                person_tag_counts[tag] = person_tag_counts.get(tag, 0) + 1
        top3 = sorted(person_tag_counts.items(), key=lambda x: -x[1])[:3]
        tags_str = ""
        if top3:
            tags_str = "\n   🏷 " + ", ".join(f"{tag} ({cnt})" for tag, cnt in top3)

        lines.append(f"👤 *{short}* — {count} задач | ⏱ {hours}ч {minutes}мин{tags_str}")

    if top_tags:
        lines.append("\n🏷 *Топ тегов:*")
        for tag, cnt in top_tags:
            lines.append(f"   • {tag} — {cnt}")

    text = "\n".join(lines)

    # Кнопки по каждому сотруднику (короткое имя)
    keyboard = []
    row = []
    for i, (name, data) in enumerate(sorted_responsible):
        parts = name.split()
        short = f"{parts[-1]} {parts[0][0]}." if len(parts) >= 2 else name
        # Сохраняем индекс сотрудника как callback
        row.append(InlineKeyboardButton(short, callback_data=f"tasks_person_{i}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔄 Выбрать другую группу", callback_data="back_to_groups")])

    # Сохраняем порядок сотрудников
    context.user_data["tasks_persons"] = [name for name, _ in sorted_responsible]

    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.edit_message_text(text.replace("*", ""), reply_markup=InlineKeyboardMarkup(keyboard))


async def tasks_person_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальный список задач по конкретному сотруднику."""
    query = update.callback_query
    await query.answer()

    idx = int(query.data.replace("tasks_person_", ""))
    persons = context.user_data.get("tasks_persons", [])
    task_list = context.user_data.get("task_list", [])
    filter_label = context.user_data.get("filter_label", "")
    group_label = context.user_data.get("group_label", "")

    if idx >= len(persons):
        await query.edit_message_text("❌ Данные устарели, запросите задачи заново.")
        return

    name = persons[idx]
    person_tasks = [t for t in task_list if t.get("responsible_name") == name]

    lines = [f"{filter_label} — *{group_label}*\n👤 *{name}* ({len(person_tasks)}):\n"]
    for t in person_tasks:
        stage_name = t.get("stage_name", "")
        if not stage_name:
            stage_name = STATUS_LABELS.get(str(t.get("status", "1")), "❓")
        status = stage_name
        title = t.get("title", "Без названия")
        deadline = t.get("deadline", "")
        deadline_str = f"⏰ {deadline[:10]}" if deadline else "⏰ не указан"
        time_spent = int(t.get("time_spent_seconds", 0) or 0)
        hours = time_spent // 3600
        minutes = (time_spent % 3600) // 60
        time_str = f"⏱ {hours}ч {minutes}мин"
        task_id = t.get("id", "")
        task_url = f"https://mfportal.by/company/personal/user/0/tasks/task/view/{task_id}/"
        tags = t.get("tags", [])
        tags_str = f"\n   🏷 {', '.join(tags)}" if tags else ""
        lines.append(f"• [{title}]({task_url})\n   {status} | {deadline_str} | {time_str}{tags_str}")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n\n_...список обрезан_"

    keyboard = [
        [InlineKeyboardButton("🔙 Назад к сводке", callback_data=f"filter_{context.user_data.get('filter_type', 'important')}")],
        [InlineKeyboardButton("🔄 Выбрать другую группу", callback_data="back_to_groups")],
    ]
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
            InlineKeyboardButton("🛠 ТП", callback_data="group_ТП"),
        ],
        [
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
            InlineKeyboardButton("🛠 ТП", callback_data="anal_ТП"),
        ],
        [
            InlineKeyboardButton("📋 Все", callback_data="anal_ALL"),
        ],
    ]
    await update.message.reply_text("📊 Аналитика — выбери группу:", reply_markup=InlineKeyboardMarkup(keyboard))


async def analytics_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group = query.data.replace("anal_", "")
    context.user_data["anal_group"] = group

    # ТП — своё меню
    if group == "ТП":
        keyboard = [
            [
                InlineKeyboardButton("👥 Сопровождение розницы", callback_data="tp_group_retail"),
                InlineKeyboardButton("🖥 Системные администраторы", callback_data="tp_group_sysadmin"),
            ],
            [InlineKeyboardButton("🔙 Назад", callback_data="anal_back")],
        ]
        await query.edit_message_text(
            "🛠 *Техническая поддержка* — выбери подгруппу:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    group_label = group if group != "ALL" else "Все группы"
    keyboard = [[
        InlineKeyboardButton("⚡ Быстрый (500 задач)", callback_data="anal_type_quick"),
        InlineKeyboardButton("🔍 Полный (за год)", callback_data="anal_type_full"),
    ]]
    await query.edit_message_text(
        f"Группа: *{group_label}*\nВыбери тип анализа:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def tp_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор подгруппы ТП → меню трёх отчётов."""
    query = update.callback_query
    await query.answer()
    tp_group = query.data.replace("tp_group_", "")
    context.user_data["tp_group"] = tp_group
    label = "👥 Сопровождение розницы" if tp_group == "retail" else "🖥 Системные администраторы"
    keyboard = [
        [InlineKeyboardButton("📋 В работе", callback_data="tp_report_active")],
        [InlineKeyboardButton("🔴 Просроченные", callback_data="tp_report_overdue")],
        [InlineKeyboardButton("⏰ Долгие (>7 дней) + нераспред. (>2 дней)", callback_data="tp_report_long")],
        [InlineKeyboardButton("🔙 Назад", callback_data="anal_ТП")],
    ]
    await query.edit_message_text(
        f"{label} — выбери отчёт:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def tp_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Формирует и показывает отчёт по ТП — сводка по сотрудникам + детали по кнопке."""
    query = update.callback_query
    await query.answer()

    report_type = query.data.replace("tp_report_", "")
    tp_group = context.user_data.get("tp_group", "retail")
    label = "👥 Сопровождение розницы" if tp_group == "retail" else "🖥 Системные администраторы"

    from db import TP_RETAIL, TP_SYSADMIN, get_tp_active, get_tp_overdue, get_tp_long, get_tp_unassigned
    user_ids = TP_RETAIL if tp_group == "retail" else TP_SYSADMIN

    await query.edit_message_text(f"⏳ Загружаю данные...")

    back_keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data=f"tp_group_{tp_group}")]]

    if report_type == "active":
        tasks = get_tp_active(user_ids)
        report_label = "📋 В работе"
    elif report_type == "overdue":
        tasks = get_tp_overdue(user_ids)
        report_label = "🔴 Просроченные"
    elif report_type == "long":
        long_tasks = get_tp_long(user_ids, days=7)
        unassigned = get_tp_unassigned(days=2)
        # Объединяем для показа по сотрудникам
        tasks = long_tasks
        report_label = "⏰ Долгие (>7 дней)"
    else:
        await query.edit_message_text("❌ Неизвестный тип отчёта.")
        return

    if report_type == "long":
        # Для долгих показываем два блока: по сотрудникам + нераспределённые
        by_person = {}
        for t in long_tasks:
            name = t.get("responsible_name", "Не указан")
            if name not in by_person:
                by_person[name] = []
            by_person[name].append(t)
        sorted_persons = sorted(by_person.items(), key=lambda x: -len(x[1]))

        lines = [f"⏰ *{label}*\n*В работе >7 дней ({len(long_tasks)}):*\n"]
        for name, ptasks in sorted_persons:
            parts = name.split()
            short = f"{parts[-1]} {parts[0][0]}." if len(parts) >= 2 else name
            lines.append(f"👤 *{short}* ({len(ptasks)})")
            for t in ptasks:
                from datetime import datetime
                try:
                    days_in = (datetime.now() - datetime.fromisoformat(t["created_date"])).days
                except Exception:
                    days_in = 0
                tid = t.get("id", "")
                url = f"https://mfportal.by/company/personal/user/0/tasks/task/view/{tid}/"
                stage = t.get("stage_name") or STATUS_LABELS.get(t.get("status", "1"), "—")
                deadline = t.get("deadline", "")[:10] if t.get("deadline") else "не указан"
                lines.append(f"   • [{t['title']}]({url})\n     {stage} | {days_in} дн. | ⏰ {deadline}")

        lines.append(f"\n*Нераспределённые >2 дней ({len(unassigned)}):*")
        if unassigned:
            for t in unassigned:
                from datetime import datetime
                try:
                    days_in = (datetime.now() - datetime.fromisoformat(t["created_date"])).days
                except Exception:
                    days_in = 0
                tid = t.get("id", "")
                url = f"https://mfportal.by/company/personal/user/0/tasks/task/view/{tid}/"
                lines.append(f"   • [{t['title']}]({url}) — {days_in} дн.")
        else:
            lines.append("_Нет таких заявок_")

        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n\n_...список обрезан_"
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_keyboard))
        except Exception:
            await query.edit_message_text(text.replace("*", "").replace("_", ""), reply_markup=InlineKeyboardMarkup(back_keyboard))
        return

    if not tasks:
        msg = "📭 Нет активных задач." if report_type == "active" else "✅ Просроченных задач нет."
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(back_keyboard))
        return

    # Группируем по сотруднику
    by_person = {}
    for t in tasks:
        name = t.get("responsible_name", "Не указан")
        if name not in by_person:
            by_person[name] = []
        by_person[name].append(t)
    sorted_persons = sorted(by_person.items(), key=lambda x: -len(x[1]))

    # Сохраняем для детального просмотра
    context.user_data["tp_tasks"] = tasks
    context.user_data["tp_persons"] = [name for name, _ in sorted_persons]
    context.user_data["tp_report_type"] = report_type
    context.user_data["tp_report_label"] = report_label

    # Сводка
    lines = [f"{report_label} — *{label}* ({len(tasks)}):\n"]
    for name, ptasks in sorted_persons:
        parts = name.split()
        short = f"{parts[-1]} {parts[0][0]}." if len(parts) >= 2 else name
        lines.append(f"👤 *{short}* — {len(ptasks)} задач")

    text = "\n".join(lines)

    # Кнопки по каждому сотруднику
    keyboard = []
    row = []
    for i, (name, _) in enumerate(sorted_persons):
        parts = name.split()
        short = f"{parts[-1]} {parts[0][0]}." if len(parts) >= 2 else name
        row.append(InlineKeyboardButton(short, callback_data=f"tp_person_{i}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"tp_group_{tp_group}")])

    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.edit_message_text(text.replace("*", ""), reply_markup=InlineKeyboardMarkup(keyboard))


async def tp_person_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальный список задач по конкретному сотруднику ТП."""
    query = update.callback_query
    await query.answer()

    idx = int(query.data.replace("tp_person_", ""))
    persons = context.user_data.get("tp_persons", [])
    tasks = context.user_data.get("tp_tasks", [])
    report_label = context.user_data.get("tp_report_label", "")
    tp_group = context.user_data.get("tp_group", "retail")
    report_type = context.user_data.get("tp_report_type", "active")

    if idx >= len(persons):
        await query.edit_message_text("❌ Данные устарели, запросите отчёт заново.")
        return

    name = persons[idx]
    person_tasks = [t for t in tasks if t.get("responsible_name") == name]

    lines = [f"{report_label}\n👤 *{name}* ({len(person_tasks)}):\n"]
    from datetime import datetime
    for t in person_tasks:
        tid = t.get("id", "")
        url = f"https://mfportal.by/company/personal/user/0/tasks/task/view/{tid}/"
        stage = t.get("stage_name") or STATUS_LABELS.get(t.get("status", "1"), "—")
        deadline = t.get("deadline", "")[:10] if t.get("deadline") else "не указан"
        try:
            days_in = (datetime.now() - datetime.fromisoformat(t["created_date"])).days
        except Exception:
            days_in = 0
        lines.append(f"• [{t['title']}]({url})\n   {stage} | {days_in} дн. | ⏰ {deadline}")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n\n_...список обрезан_"

    keyboard = [
        [InlineKeyboardButton("🔙 К сводке", callback_data=f"tp_report_{report_type}")],
        [InlineKeyboardButton("🔙 Назад", callback_data=f"tp_group_{tp_group}")],
    ]
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.edit_message_text(text.replace("*", "").replace("_", ""), reply_markup=InlineKeyboardMarkup(keyboard))

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
    d = result.get("developer", {"by_person": {}})
    analyzed = result.get("analyzed") or result.get("total_closed", 0)

    # Сохраняем для меню "По специалисту" — только реальные участники группы
    context.user_data["spec_by_person"] = {
        "analyst": a.get("by_person", {}),
        "tester": t.get("by_person", {}),
        "developer": d.get("by_person", {}),
    }

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
        [InlineKeyboardButton("👤 По специалисту", callback_data="anal_specialist")],
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
            InlineKeyboardButton("🛠 ТП", callback_data="anal_ТП"),
        ],
        [
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
async def analytics_specialist_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор роли специалиста для детального анализа."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [
            InlineKeyboardButton("👨‍💼 Аналитики", callback_data="spec_role_analyst"),
            InlineKeyboardButton("🧪 Тестировщики", callback_data="spec_role_tester"),
        ],
        [InlineKeyboardButton("👨‍💻 Разработчики", callback_data="spec_role_developer")],
        [InlineKeyboardButton("🔙 Назад", callback_data="anal_back")],
    ]
    await query.edit_message_text("Выбери роль специалиста:", reply_markup=InlineKeyboardMarkup(keyboard))
async def analytics_specialist_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список специалистов выбранной роли."""
    query = update.callback_query
    await query.answer()
    role = query.data.replace("spec_role_", "")
    context.user_data["spec_role"] = role

    from analytics import get_specialists_list
    by_person = context.user_data.get("spec_by_person", {}).get(role, {})
    specialists = get_specialists_list(role, by_person)

    if not specialists:
        await query.edit_message_text(
            "❌ Специалисты не найдены в текущей выборке. Сначала выполните аналитику по группе.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="anal_specialist")]])
        )
        return

    keyboard = []
    for s in specialists[:20]:  # максимум 20 кнопок
        short_name = " ".join(s["name"].split()[:2])  # Фамилия Имя
        keyboard.append([InlineKeyboardButton(short_name, callback_data=f"spec_id_{s['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="anal_specialist")])

    role_label = "аналитиков" if role == "analyst" else "тестировщиков"
    await query.edit_message_text(
        f"Выбери специалиста из списка {role_label}:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def analytics_specialist_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальная аналитика по специалисту."""
    query = update.callback_query
    await query.answer()
    user_id = query.data.replace("spec_id_", "")

    await query.edit_message_text("⏳ Загружаю аналитику по специалисту...")

    from analytics import specialist_analytics
    result = specialist_analytics(user_id)

    if not result["success"]:
        await query.edit_message_text(f"❌ Ошибка: {result.get('error')}")
        return

    r = result["responsible"]
    a = result["accomplice"]

    def make_bar(pct):
        """5 кружочков: 🔴 зона 0-20%, 🟡 зона 20-60%, 🟢 зона 60-100%."""
        filled = pct // 20  # сколько кружочков закрашено (0-5)
        circles = []
        for i in range(5):
            if i >= filled:
                circles.append("⚪")
            elif i == 0:
                circles.append("🔴")
            elif i <= 2:
                circles.append("🟡")
            else:
                circles.append("🟢")
        return "".join(circles)

    resp_bar = make_bar(r["closed_pct"])
    acc_bar = make_bar(a["closed_pct"])

    # Совместное участие — заголовок зависит от роли специалиста
    spec_role = context.user_data.get('spec_role', 'analyst')
    collab_label = "с аналитиком/тестировщиком" if spec_role == "developer" else "с разработчиком"
    collab_tasks = result.get('collab_tasks', 0)
    collab_total = result.get('collab_total', 0)
    collab_pct = round(collab_tasks / collab_total * 100, 1) if collab_total > 0 else 0

    # Списанные часы
    user_minutes = result.get('user_minutes', 0)
    total_minutes = result.get('total_minutes', 0)
    user_hours = round(user_minutes / 60, 1)
    hours_pct = round(user_minutes / total_minutes * 100, 1) if total_minutes > 0 else 0
    total_hours = round(total_minutes / 60, 1)

    text = (
        f"👤 *{result['name']}*\n"
        f"_{result['position']}_\n\n"
        f"*📋 Как исполнитель* (за год + активные):\n"
        f"Всего задач: *{r['total']}*\n"
        f"✅ Закрытых: *{r['closed']}* ({r['closed_pct']}%)\n"
        f"⏳ Активных: *{r['open']}*\n"
        f"{resp_bar}\n\n"
        f"*🤝 Как соисполнитель* (за год + активные):\n"
        f"Всего задач: *{a['total']}*\n"
        f"✅ Закрытых: *{a['closed']}* ({a['closed_pct']}%)\n"
        f"⏳ Активных: *{a['open']}*\n"
        f"{acc_bar}\n\n"
        f"*👥 Совместные задачи {collab_label}:*\n"
        f"Задач: *{collab_tasks}* из {collab_total} ({collab_pct}%)\n\n"
        f"*⏱ Списанное время за год:*\n"
        f"Специалист списал: *{user_hours} ч*\n"
        f"Все участники задач: *{total_hours} ч*\n"
        f"Доля специалиста: *{hours_pct}%*\n\n"
        f"*🔄 Возвраты на доработку за год:*\n"
        f"Задач с возвратами: *{result['returns_tasks']}*\n"
        f"Всего событий возврата: *{result['returns_events']}* раз\n"
    )

    # Считаем проценты возвратов
    rt = result['returns_tasks']
    re_ = result['returns_events']
    total_all = r['total'] + a['total']
    pct_of_total = round(rt / total_all * 100, 1) if total_all > 0 else 0
    pct_of_resp = round(rt / r['total'] * 100, 1) if r['total'] > 0 else 0
    avg_per_task = round(re_ / rt, 2) if rt > 0 else 0

    text += (
        f"• % от всех задач: *{pct_of_total}%* ({rt} из {total_all})\n"
        f"• % от задач как исполнитель: *{pct_of_resp}%* ({rt} из {r['total']})\n"
        f"• Среднее возвратов на задачу: *{avg_per_task}* раз\n"
        f"_(учитываются все задачи где специалист исполнитель/соисполнитель, включая уже закрытые)_\n"
    )
    if result.get("returns_db_error"):
        text += f"\n⚠️ _Ошибка БД: {result['returns_db_error']}_\n"

    keyboard = [
        [InlineKeyboardButton("🔙 К списку", callback_data=f"spec_role_{context.user_data.get('spec_role', 'analyst')}")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="anal_back")],
    ]
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.edit_message_text(text.replace("*", "").replace("_", ""), reply_markup=InlineKeyboardMarkup(keyboard))       

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
    app.add_handler(CallbackQueryHandler(tasks_person_callback, pattern="^tasks_person_"))
    app.add_handler(CallbackQueryHandler(back_to_groups, pattern="^back_to_groups$"))
    app.add_handler(CallbackQueryHandler(calendar_callback, pattern="^cal_"))
    app.add_handler(meeting_handler)
    app.add_handler(CommandHandler("analytics", analytics))
    app.add_handler(CallbackQueryHandler(analytics_group_callback, pattern="^anal_(?!type_|back|specialist|returns_)"))
    app.add_handler(CallbackQueryHandler(analytics_type_callback, pattern="^anal_type_"))
    app.add_handler(CallbackQueryHandler(analytics_back_callback, pattern="^anal_back$"))
    app.add_handler(CommandHandler("resetall", resetall))
    app.add_handler(CallbackQueryHandler(analytics_returns_callback, pattern="^anal_returns_"))
    app.add_handler(CallbackQueryHandler(analytics_specialist_role, pattern="^anal_specialist$"))
    app.add_handler(CallbackQueryHandler(analytics_specialist_list, pattern="^spec_role_"))
    app.add_handler(CallbackQueryHandler(analytics_specialist_detail, pattern="^spec_id_"))
    app.add_handler(CallbackQueryHandler(tp_group_callback, pattern="^tp_group_"))
    app.add_handler(CallbackQueryHandler(tp_report_callback, pattern="^tp_report_"))
    app.add_handler(CallbackQueryHandler(tp_person_callback, pattern="^tp_person_"))

    print("🤖 Бот запущен! Нажми Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
