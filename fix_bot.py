code = open("bot.py", "rb").read().decode("utf-8", errors="replace")
print(repr(code[:500]))