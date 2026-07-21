"""Test si el módulo editor se puede importar."""
import sys
from pathlib import Path

log_file = Path("test_import.txt")

with open(log_file, "w", encoding="utf-8") as f:
    f.write("PRUEBA DE IMPORTACIÓN DEL MÓDULO EDITOR\n")
    f.write("="*60 + "\n\n")
    
    try:
        f.write("1. Importando módulo...\n")
        f.flush()
        
        from app.stickers.editor import StickerStudio
        
        f.write("   ✓ Importación exitosa\n\n")
        f.write("2. Verificando método process_queue...\n")
        f.flush()
        
        if hasattr(StickerStudio, 'process_queue'):
            f.write("   ✓ Método process_queue existe\n")
        else:
            f.write("   ✗ Método process_queue NO EXISTE\n")
        
        f.write("\n3. Métodos disponibles:\n")
        methods = [m for m in dir(StickerStudio) if not m.startswith('_') and callable(getattr(StickerStudio, m))]
        for method in sorted(methods)[:20]:
            f.write(f"   - {method}\n")
        
        f.write("\n✓ ÉXITO: El módulo se importó correctamente\n")
        
    except SyntaxError as e:
        f.write(f"\n✗ ERROR DE SINTAXIS:\n")
        f.write(f"   Línea {e.lineno}: {e.msg}\n")
        f.write(f"   {e.text}\n")
        
    except Exception as e:
        f.write(f"\n✗ ERROR AL IMPORTAR:\n")
        f.write(f"   {type(e).__name__}: {e}\n")
        
        import traceback
        f.write("\nTraceback:\n")
        f.write(traceback.format_exc())

print(f"Resultado en: {log_file.absolute()}")
