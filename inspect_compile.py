import traceback

try:
    with open("app/stickers/editor.py", "r", encoding="utf-8") as f:
        source = f.read()
    compile(source, "app/stickers/editor.py", "exec")
    print("Compilation succeeded!")
except SyntaxError as e:
    print("SyntaxError caught:")
    print("  msg:", e.msg)
    print("  lineno:", e.lineno)
    print("  offset:", e.offset)
    print("  text:", repr(e.text))
    traceback.print_exc()
