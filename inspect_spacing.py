with open("app/stickers/editor.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for idx in range(1265, 1285):
    if idx < len(lines):
        line = lines[idx]
        print(f"Line {idx+1}: {repr(line)}")
