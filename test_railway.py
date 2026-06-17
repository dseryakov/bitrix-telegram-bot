import os
from dotenv import load_dotenv
load_dotenv()

print("DB_HOST:", repr(os.getenv("DB_HOST")))
print("DB_PORT:", repr(os.getenv("DB_PORT")))
print("DB_USER:", repr(os.getenv("DB_USER")))
print("DB_NAME:", repr(os.getenv("DB_NAME")))

import pymysql
try:
    conn = pymysql.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME", "sitemanager0"),
        port=int(os.getenv("DB_PORT", "3306")),
        connect_timeout=5,
        cursorclass=pymysql.cursors.DictCursor
    )
    print("OK - connected")
    conn.close()
except Exception as e:
    print("FAIL:", e)