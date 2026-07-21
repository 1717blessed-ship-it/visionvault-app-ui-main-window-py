Automatización del proyecto

Scripts disponibles:

- `tools\run_all.ps1`  : PowerShell runner que ejecuta `pytest` y `tools/verify_selection.py`. Pasar `-RunUI` para además abrir `main.py`.
- `tools\automation.py`: Script multiplataforma Python que ejecuta las mismas tareas. Usar `--run-ui` para lanzar la UI.
- `tools\verify_selection.py`: verificador rápido que simula `_apply_area_selection`.

Ejecutar todo (PowerShell):

```powershell
cd path\to\project
.\tools\run_all.ps1
```

Ejecutar todo (Python runner):

```bash
python tools/automation.py
# con UI
python tools/automation.py --run-ui
```

Notas:
- Las pruebas GUI usan `tkinter` y deben ejecutarse en un entorno con pantalla interactiva.
- Si faltan dependencias (OpenCV, rembg, etc.), los tests de lógica seguirán ejecutándose con los fallbacks implementados en el código.
