from pathlib import Path
import traceback


def run():
    from app.ui.main_window import VisionVaultApp

    VisionVaultApp().mainloop()


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        # Al iniciarse desde el escritorio no hay consola: muestra el problema en pantalla.
        details = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        log_path = Path(__file__).with_name("error_inicio_doccione.log")
        try:
            log_path.write_text(details, encoding="utf-8")
        except OSError:
            pass
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Doccione no pudo abrirse",
            f"{error}\n\nSe guardó el detalle en:\n{log_path}",
        )
        root.destroy()
