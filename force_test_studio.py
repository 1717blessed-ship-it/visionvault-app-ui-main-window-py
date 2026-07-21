"""Forzar test del StickerStudio escribiendo a archivo."""
import sys
from pathlib import Path

log_file = Path("force_test_output.txt")

with open(log_file, "w", encoding="utf-8") as log:
    log.write("INICIO DEL TEST\n")
    log.write("=" * 60 + "\n\n")
    log.flush()
    
    try:
        log.write("Paso 1: Importando tkinter...\n")
        log.flush()
        import tkinter as tk
        log.write("OK\n\n")
        log.flush()
        
        log.write("Paso 2: Importando Database...\n")
        log.flush()
        from app.database.database import ImageDatabase
        log.write("OK\n\n")
        log.flush()
        
        log.write("Paso 3: Importando StickerStudio...\n")
        log.flush()
        from app.stickers.editor import StickerStudio
        log.write("OK\n\n")
        log.flush()
        
        log.write("Paso 4: Creando ventana root...\n")
        log.flush()
        root = tk.Tk()
        root.withdraw()
        log.write("OK\n\n")
        log.flush()
        
        log.write("Paso 5: Abriendo base de datos...\n")
        log.flush()
        db = ImageDatabase("visionvault.db")
        log.write("OK\n\n")
        log.flush()
        
        log.write("Paso 6: Creando StickerStudio...\n")
        log.flush()
        studio = StickerStudio(root, db)
        log.write("OK\n\n")
        log.flush()
        
        log.write("Paso 7: Limpiando...\n")
        log.flush()
        studio.destroy()
        root.destroy()
        log.write("OK\n\n")
        log.flush()
        
        log.write("=" * 60 + "\n")
        log.write("EXITO: Todo funciona correctamente\n")
        log.write("=" * 60 + "\n")
        
    except Exception as e:
        import traceback
        log.write("\n")
        log.write("=" * 60 + "\n")
        log.write("ERROR ENCONTRADO\n")
        log.write("=" * 60 + "\n\n")
        log.write(f"Error: {e}\n")
        log.write(f"Tipo: {type(e).__name__}\n\n")
        log.write("Traceback completo:\n")
        log.write(traceback.format_exc())
        log.write("\n")

print(f"Test completado. Resultado en: {log_file.absolute()}")
