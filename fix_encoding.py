with open("bot.py", "rb") as f:
    content = f.read()

# Найдём позицию строки с anal_specialist
idx = content.find(b"anal_specialist")
print(repr(content[idx-100:idx+50]))