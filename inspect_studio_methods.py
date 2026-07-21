import marshal

pyc_path = r"c:\Users\Win 10\Documents\Codex\2026-07-13\visionvault-app-ui-main-window-py\app\stickers\__pycache__\editor.cpython-313.pyc"

with open(pyc_path, "rb") as f:
    f.read(16)
    code_obj = marshal.load(f)

# Find StickerStudio
for const in code_obj.co_consts:
    if hasattr(const, 'co_name') and const.co_name == 'StickerStudio':
        print("StickerStudio co_names:")
        print(const.co_names)
        print("\nStickerStudio co_consts (method names):")
        for c in const.co_consts:
            if hasattr(c, 'co_name'):
                print(f"  {c.co_name}")
