from analytics import quick_analytics
import json

result = quick_analytics("WEB")
print(json.dumps(result["analyst"]["by_person"], ensure_ascii=False, indent=2))
print(json.dumps(result["tester"]["by_person"], ensure_ascii=False, indent=2))