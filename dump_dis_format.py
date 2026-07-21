import marshal
import dis

pyc_path = r"c:\Users\Win 10\Documents\Codex\2026-07-13\visionvault-app-ui-main-window-py\app\stickers\__pycache__\editor.cpython-313.pyc"

with open(pyc_path, "rb") as f:
    f.read(16)
    code_obj = marshal.load(f)

# Find StickerStudio
studio_code = None
for const in code_obj.co_consts:
    if hasattr(const, 'co_name') and const.co_name == 'StickerStudio':
        studio_code = const

if studio_code:
    for const in studio_code.co_consts:
        if hasattr(const, 'co_name') and const.co_name == '_format_queue_filename':
            print("=== DISASSEMBLY OF _format_queue_filename ===")
            dis.dis(const)
