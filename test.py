from analytics import specialist_analytics
import json

result = specialist_analytics("83974")
print(json.dumps(result, ensure_ascii=False, indent=2))