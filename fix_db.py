with open("db.py", "rb") as f:
    content = f.read()

old = b"RETURN_STAGES = ('\xd0\x9f\xd1\x80\xd0\xb0\xd0\xb2\xd0\xba\xd0\xb8/\xd0\x94\xd0\xbe\xd1\x80\xd0\xb0\xd0\xb1\xd0\xbe\xd1\x82\xd0\xba\xd0\xb8'"
new = b"RETURN_STAGES = ('\xd0\x9f\xd1\x80\xd0\xb0\xd0\xb2\xd0\xba\xd0\xb8/\xd0\x94\xd0\xbe\xd1\x80\xd0\xb0\xd0\xb1\xd0\xbe\xd1\x82\xd0\xba\xd0\xb8'"

# Проще — заменим всю строку
lines = content.split(b'\n')
new_lines = []
for line in lines:
    if b'RETURN_STAGES' in line and b'STAGE' not in line:
        new_lines.append("RETURN_STAGES = ('Правки/Доработки', 'Возврат на доработку', 'На доработке')".encode('utf-8'))
    else:
        new_lines.append(line)

with open("db.py", "wb") as f:
    f.write(b'\n'.join(new_lines))
print("Done")