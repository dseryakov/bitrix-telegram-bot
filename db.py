"""
Прямое подключение к БД Битрикс24 для получения истории возвратов.
"""

import pymysql
import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME", "sitemanager0")
DB_PORT = int(os.getenv("DB_PORT", "3306"))

RETURN_STAGES = ('Правки/Доработки', 'Возврат на доработку', 'На доработке')


def get_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=DB_PORT,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
    )


def get_task_return_counts(task_ids: list) -> dict:
    """
    Получить количество возвратов для списка задач.
    Возвращает {task_id: return_count}
    """
    if not task_ids:
        return {}

    placeholders = ','.join(['%s'] * len(task_ids))
    query = f"""
        SELECT TASK_ID, COUNT(*) as return_count
        FROM b_tasks_log
        WHERE FIELD = 'STAGE'
        AND TO_VALUE IN %s
        AND TASK_ID IN ({placeholders})
        GROUP BY TASK_ID
    """

    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, [RETURN_STAGES] + [int(tid) for tid in task_ids])
            rows = cursor.fetchall()
        conn.close()
        return {str(row['TASK_ID']): row['return_count'] for row in rows}
    except Exception as e:
        print(f"DB error: {e}")
        return {}


def get_specialist_return_stats(user_id: str, year_ago: str) -> dict:
    """
    Получить статистику возвратов для конкретного специалиста за период.
    user_id — строковый ID пользователя Битрикс24.
    year_ago — дата в формате 'YYYY-MM-DD'.
    Возвращает {'tasks': int, 'events': int}.
    """
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(DISTINCT tl.TASK_ID) as tasks, COUNT(*) as events
                FROM b_tasks_log tl
                JOIN b_tasks t ON t.ID = tl.TASK_ID
                WHERE tl.FIELD = 'STAGE'
                AND tl.TO_VALUE IN %s
                AND tl.CREATED_DATE >= %s
                AND (
                    t.RESPONSIBLE_ID = %s
                    OR tl.TASK_ID IN (
                        SELECT TASK_ID FROM b_tasks_member
                        WHERE USER_ID = %s AND TYPE IN ('A', 'C')
                    )
                )
            """, [RETURN_STAGES, year_ago, int(user_id), int(user_id)])
            row = cursor.fetchone()
        conn.close()
        return {
            'tasks': int(row['tasks']) if row and row['tasks'] else 0,
            'events': int(row['events']) if row and row['events'] else 0,
        }
    except Exception as e:
        print(f"DB error get_specialist_return_stats: {e}")
        return {'tasks': 0, 'events': 0, 'error': str(e)}


def get_group_return_stats(group_ids: list, year_ago: str) -> dict:
    """
    Получить статистику возвратов по группам за период.
    Возвращает {task_id: return_count} для задач с возвратами.
    """
    placeholders = ','.join(['%s'] * len(group_ids))
    query = f"""
        SELECT tl.TASK_ID, COUNT(*) as return_count
        FROM b_tasks_log tl
        JOIN b_tasks t ON t.ID = tl.TASK_ID
        WHERE tl.FIELD = 'STAGE'
        AND tl.TO_VALUE IN %s
        AND t.GROUP_ID IN ({placeholders})
        AND tl.CREATED_DATE >= %s
        GROUP BY tl.TASK_ID
    """
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, [RETURN_STAGES] + group_ids + [year_ago])
            rows = cursor.fetchall()
        conn.close()
        return {str(row['TASK_ID']): row['return_count'] for row in rows}
    except Exception as e:
        print(f"DB error get_group_return_stats: {e}")
        return {}


# Ключевые слова должностей разработчиков (синхронизировать с analytics.py)
DEVELOPER_KEYWORDS = ["программист", "разработч", "инженер", "teamlead", "team lead",
                      "руководитель отдела разработки", "начальник отдела разработки"]


# Ключевые слова должностей аналитиков и тестировщиков (для совместности разработчика)
ANALYST_TESTER_KEYWORDS = ["аналитик", "тестировщик", "тестер", "qa"]


def get_specialist_collab_stats(user_id: str, year_ago: str, target_keywords: list = None) -> dict:
    """
    Совместное участие специалиста с другой ролью (по умолчанию — с разработчиками).
    target_keywords: список ключевых слов должности для поиска "коллег" в задаче
                      (например ANALYST_TESTER_KEYWORDS для совместности разработчика
                      с аналитиками/тестировщиками).
    Возвращает {'collab_tasks': int, 'total_tasks': int}.
    """
    if target_keywords is None:
        target_keywords = DEVELOPER_KEYWORDS
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            # Все задачи специалиста за год (исполнитель или соисполнитель)
            cursor.execute("""
                SELECT DISTINCT t.ID as task_id
                FROM b_tasks t
                LEFT JOIN b_tasks_member m ON m.TASK_ID = t.ID AND m.USER_ID = %s AND m.TYPE IN ('A', 'C')
                WHERE (t.RESPONSIBLE_ID = %s OR m.TASK_ID IS NOT NULL)
                AND t.CREATED_DATE >= %s
            """, [int(user_id), int(user_id), year_ago])
            all_tasks = [row['task_id'] for row in cursor.fetchall()]

            if not all_tasks:
                conn.close()
                return {'collab_tasks': 0, 'total_tasks': 0}

            # Из них — задачи где есть хотя бы один участник с целевой ролью
            placeholders = ','.join(['%s'] * len(all_tasks))
            target_conditions = ' OR '.join([f"u.WORK_POSITION LIKE %s" for _ in target_keywords])
            target_params = [f"%{k}%" for k in target_keywords]

            cursor.execute(f"""
                SELECT COUNT(DISTINCT m2.TASK_ID) as collab_tasks
                FROM b_tasks_member m2
                JOIN b_user u ON u.ID = m2.USER_ID
                WHERE m2.TASK_ID IN ({placeholders})
                AND m2.USER_ID != %s
                AND ({target_conditions})
            """, all_tasks + [int(user_id)] + target_params)

            row = cursor.fetchone()
            collab = int(row['collab_tasks']) if row and row['collab_tasks'] else 0

        conn.close()
        return {'collab_tasks': collab, 'total_tasks': len(all_tasks)}
    except Exception as e:
        print(f"DB error get_specialist_collab_stats: {e}")
        return {'collab_tasks': 0, 'total_tasks': 0, 'error': str(e)}


def get_specialist_hours_stats(user_id: str, year_ago: str) -> dict:
    """
    Списанные часы специалиста и % от всех участников его задач.
    Возвращает {'user_minutes': int, 'total_minutes': int}.
    """
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            # Задачи специалиста за год
            cursor.execute("""
                SELECT DISTINCT t.ID as task_id
                FROM b_tasks t
                LEFT JOIN b_tasks_member m ON m.TASK_ID = t.ID AND m.USER_ID = %s AND m.TYPE IN ('A', 'C')
                WHERE (t.RESPONSIBLE_ID = %s OR m.TASK_ID IS NOT NULL)
                AND t.CREATED_DATE >= %s
            """, [int(user_id), int(user_id), year_ago])
            task_ids = [row['task_id'] for row in cursor.fetchall()]

            if not task_ids:
                conn.close()
                return {'user_minutes': 0, 'total_minutes': 0}

            placeholders = ','.join(['%s'] * len(task_ids))

            # Часы самого специалиста
            cursor.execute(f"""
                SELECT COALESCE(SUM(MINUTES), 0) as mins
                FROM b_tasks_elapsed_time
                WHERE USER_ID = %s AND TASK_ID IN ({placeholders})
                AND CREATED_DATE >= %s
            """, [int(user_id)] + task_ids + [year_ago])
            row = cursor.fetchone()
            user_minutes = int(row['mins']) if row and row['mins'] else 0

            # Все часы по этим задачам (все участники)
            cursor.execute(f"""
                SELECT COALESCE(SUM(MINUTES), 0) as mins
                FROM b_tasks_elapsed_time
                WHERE TASK_ID IN ({placeholders})
                AND CREATED_DATE >= %s
            """, task_ids + [year_ago])
            row = cursor.fetchone()
            total_minutes = int(row['mins']) if row and row['mins'] else 0

        conn.close()
        return {'user_minutes': user_minutes, 'total_minutes': total_minutes}
    except Exception as e:
        print(f"DB error get_specialist_hours_stats: {e}")
        return {'user_minutes': 0, 'total_minutes': 0, 'error': str(e)}


def get_tasks_db(group_ids: list, filter_type: str = "important") -> list:
    """
    Быстрый список задач напрямую из MySQL — замена REST tasks.task.list + цикл комментариев.
    filter_type: "important" — приоритет=2, статус активный (1,2,3)
                 "overdue"   — приоритет=2, статус=5 (просрочено по дедлайну)
    Возвращает список словарей с полями id, title, stage_name, deadline, responsible_name,
    responsible_id, time_spent_seconds.
    """
    placeholders = ','.join(['%s'] * len(group_ids))

    if filter_type == "overdue":
        status_condition = "t.STATUS = 5"
    else:
        status_condition = "t.STATUS IN (1, 2, 3)"

    query = f"""
        SELECT
            t.ID as id,
            t.TITLE as title,
            t.STATUS as status,
            COALESCE(s.TITLE, '') as stage_name,
            t.DEADLINE as deadline,
            t.RESPONSIBLE_ID as responsible_id,
            CONCAT(COALESCE(u.NAME, ''), ' ', COALESCE(u.LAST_NAME, '')) as responsible_name,
            COALESCE(SUM(e.MINUTES), 0) * 60 as time_spent_seconds
        FROM b_tasks t
        LEFT JOIN b_user u ON u.ID = t.RESPONSIBLE_ID
        LEFT JOIN b_tasks_stages s ON s.ID = t.STAGE_ID
        LEFT JOIN b_tasks_elapsed_time e ON e.TASK_ID = t.ID
        WHERE t.GROUP_ID IN ({placeholders})
        AND t.PRIORITY = 2
        AND {status_condition}
        GROUP BY t.ID, t.TITLE, t.STATUS, s.TITLE, t.DEADLINE, t.RESPONSIBLE_ID, u.NAME, u.LAST_NAME
        ORDER BY t.DEADLINE ASC
        LIMIT 50
    """
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, group_ids)
            rows = cursor.fetchall()
        conn.close()
        result = []
        for row in rows:
            deadline = row['deadline'].strftime('%Y-%m-%dT%H:%M:%S') if row['deadline'] else ''
            result.append({
                'id': str(row['id']),
                'title': row['title'] or 'Без названия',
                'status': str(row['status']),
                'stage_name': row['stage_name'] or '',
                'deadline': deadline,
                'responsible_id': str(row['responsible_id']) if row['responsible_id'] else '',
                'responsible_name': (row['responsible_name'] or '').strip() or 'Не указан',
                'time_spent_seconds': int(row['time_spent_seconds'] or 0),
            })
        return result
    except Exception as e:
        print(f"DB error get_tasks_db: {e}")
        return []


# --- Техническая поддержка ---

TP_RETAIL = [1363, 833, 95434, 110152, 110487, 107252]   # Сопровождение розницы
TP_SYSADMIN = [59940, 64513, 22510, 119302, 98217, 78022]  # Системные администраторы
TP_ALL = TP_RETAIL + TP_SYSADMIN
TP_GROUP_ID = 102

# Базовый SELECT для задач ТП
_TP_SELECT = """
    SELECT
        t.ID as id,
        t.TITLE as title,
        t.STATUS as status,
        t.STAGE_ID as stage_id,
        COALESCE(s.TITLE, '') as stage_name,
        t.DEADLINE as deadline,
        t.CREATED_DATE as created_date,
        t.CHANGED_DATE as changed_date,
        t.RESPONSIBLE_ID as responsible_id,
        CONCAT(COALESCE(u.NAME, ''), ' ', COALESCE(u.LAST_NAME, '')) as responsible_name
    FROM b_tasks t
    LEFT JOIN b_user u ON u.ID = t.RESPONSIBLE_ID
    LEFT JOIN b_tasks_stages s ON s.ID = t.STAGE_ID
"""


def _format_tp_rows(rows):
    result = []
    for row in rows:
        deadline = row['deadline'].strftime('%Y-%m-%dT%H:%M:%S') if row['deadline'] else ''
        created = row['created_date'].strftime('%Y-%m-%dT%H:%M:%S') if row['created_date'] else ''
        changed = row['changed_date'].strftime('%Y-%m-%dT%H:%M:%S') if row['changed_date'] else ''
        result.append({
            'id': str(row['id']),
            'title': row['title'] or 'Без названия',
            'status': str(row['status']),
            'stage_id': str(row['stage_id'] or 0),
            'stage_name': row['stage_name'] or '',
            'deadline': deadline,
            'created_date': created,
            'changed_date': changed,
            'responsible_id': str(row['responsible_id']) if row['responsible_id'] else '',
            'responsible_name': (row['responsible_name'] or '').strip() or 'Не указан',
        })
    return result


def get_tp_active(user_ids: list) -> list:
    """Задачи в работе (STAGE_ID > 0, статус активный) для сотрудников ТП."""
    placeholders = ','.join(['%s'] * len(user_ids))
    query = _TP_SELECT + f"""
        WHERE t.GROUP_ID = {TP_GROUP_ID}
        AND t.STATUS IN (1, 2, 3)
        AND t.STAGE_ID > 0
        AND t.RESPONSIBLE_ID IN ({placeholders})
        ORDER BY t.DEADLINE ASC, t.CREATED_DATE ASC
        LIMIT 100
    """
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, user_ids)
            rows = cursor.fetchall()
        conn.close()
        return _format_tp_rows(rows)
    except Exception as e:
        print(f"DB error get_tp_active: {e}")
        return []


def get_tp_overdue(user_ids: list) -> list:
    """Просроченные задачи (дедлайн прошёл, статус активный) для сотрудников ТП."""
    placeholders = ','.join(['%s'] * len(user_ids))
    query = _TP_SELECT + f"""
        WHERE t.GROUP_ID = {TP_GROUP_ID}
        AND t.STATUS IN (1, 2, 3)
        AND t.DEADLINE IS NOT NULL
        AND t.DEADLINE < NOW()
        AND t.RESPONSIBLE_ID IN ({placeholders})
        ORDER BY t.DEADLINE ASC
        LIMIT 100
    """
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, user_ids)
            rows = cursor.fetchall()
        conn.close()
        return _format_tp_rows(rows)
    except Exception as e:
        print(f"DB error get_tp_overdue: {e}")
        return []


def get_tp_long(user_ids: list, days: int = 7) -> list:
    """Задачи в работе дольше N дней (по дате создания)."""
    placeholders = ','.join(['%s'] * len(user_ids))
    query = _TP_SELECT + f"""
        WHERE t.GROUP_ID = {TP_GROUP_ID}
        AND t.STATUS IN (1, 2, 3)
        AND t.STAGE_ID > 0
        AND t.CREATED_DATE <= NOW() - INTERVAL {days} DAY
        AND t.RESPONSIBLE_ID IN ({placeholders})
        ORDER BY t.CREATED_DATE ASC
        LIMIT 100
    """
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, user_ids)
            rows = cursor.fetchall()
        conn.close()
        return _format_tp_rows(rows)
    except Exception as e:
        print(f"DB error get_tp_long: {e}")
        return []


def get_tp_unassigned(days: int = 2) -> list:
    """Нераспределённые заявки (STAGE_ID=0) висящие больше N дней — топ 20 самых старых."""
    query = _TP_SELECT + f"""
        WHERE t.GROUP_ID = {TP_GROUP_ID}
        AND t.STATUS IN (1, 2, 3)
        AND t.STAGE_ID = 0
        AND t.CREATED_DATE <= NOW() - INTERVAL {days} DAY
        ORDER BY t.CREATED_DATE ASC
        LIMIT 20
    """
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, [])
            rows = cursor.fetchall()
        conn.close()
        return _format_tp_rows(rows)
    except Exception as e:
        print(f"DB error get_tp_unassigned: {e}")
        return []