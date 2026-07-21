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
        if hasattr(const, 'co_name'):
            if const.co_name == '_format_queue_filename':
                print("=== DISASSEMBLY OF _format_queue_filename ===")
                dis.dis(const)
            elif const.co_name == 'render_current':
                print("\n=== DISASSEMBLY OF render_current (FIRST HALF) ===")
                # Print only the first 200 instructions of render_current
                insts = list(dis.get_instructions(const))
                for inst in insts[:200]:
                    argval_str = f" ({inst.argval})" if inst.argval is not None else ""
                    print(f"{inst.starts_line or '' : <5} {inst.offset : <5} {inst.opname : <20} {argval_str}")
