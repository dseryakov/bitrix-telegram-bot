with open("bot.py", "r", encoding="utf-8", errors="replace") as f:
    content = f.read()

content = content.replace(
    'InlineKeyboardButton("\\u0401\\u042fС\\u0434 \\u0432\\u0430\\u043d\\u043d\\u043e\\u0435", callback_data="anal_specialist")',
    'InlineKeyboardButton("\\U0001f464 По специалисту", callback_data="anal_specialist")'
)

# Проще — заменим по частичному совпадению
lines = content.split('\n')
new_lines = []
for line in lines:
    if 'anal_specialist' in line and 'InlineKeyboardButton' in line and 'anal_specialist$' not in line and 'keyboard.append' not in line:
        new_lines.append('        [InlineKeyboardButton("👤 По специалисту", callback_data="anal_specialist")],')
    else:
        new_lines.append(line)

with open("bot.py", "w", encoding="utf-8") as f:
    f.write('\n'.join(new_lines))

print("Done")