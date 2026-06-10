with open("bot.py", "r", encoding="utf-8", errors="replace") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if 'anal_specialist' in line and 'InlineKeyboardButton' in line and 'anal_specialist$' not in line and 'keyboard.append' not in line:
        indent = len(line) - len(line.lstrip())
        new_lines.append(' ' * indent + '[InlineKeyboardButton("\U0001f464 \u041f\u043e \u0441\u043f\u0435\u0446\u0438\u0430\u043b\u0438\u0441\u0442\u0443", callback_data="anal_specialist")],\n')
    else:
        new_lines.append(line)

with open("bot.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("Done")