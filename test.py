from db import get_group_return_stats
from datetime import datetime, timedelta
import json

year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
result = get_group_return_stats([328], year_ago)
print(f"Задач с возвратами за год: {len(result)}")
print("Топ 5:", sorted(result.items(), key=lambda x: -x[1])[:5])