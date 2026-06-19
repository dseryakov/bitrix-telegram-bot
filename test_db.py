import requests, os
from dotenv import load_dotenv
load_dotenv()

WEBHOOK = os.getenv('BITRIX_WEBHOOK_URL')
r = requests.post(f"{WEBHOOK}tasks.task.get.json", json={
    "taskId": 631966,
    "select": ["ID", "TITLE", "TAGS"]
})
print(r.json())