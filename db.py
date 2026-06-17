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
        print(f"DB error: {e}")
        return {}