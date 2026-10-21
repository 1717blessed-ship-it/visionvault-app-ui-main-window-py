"""Open an isolated sticker editor for visual QA, without live integrations."""
import sys
import tempfile
from pathlib import Path
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database.database import ImageDatabase
from app.stickers.editor import StickerStudio

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='doccione-preview-') as folder:
        database = ImageDatabase(Path(folder) / 'preview.db')
        root = tk.Tk()
        root.withdraw()
        studio = StickerStudio(root, database)
        studio.bind('<Destroy>', lambda event: root.quit() if event.widget is studio else None)
        try:
            root.mainloop()
        finally:
            database.connection.close()
            root.destroy()
