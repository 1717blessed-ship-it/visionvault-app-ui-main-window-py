Presupuesto Doccione — Generador

Archivos incluidos:
- `generate_presupuesto.py` : script Python que genera el mensaje desde `precios.csv` y `pedido.csv`.
- `presupuesto_ui.html` : interfaz web local que carga los CSV y genera el presupuesto listo para copiar.

Cómo usar (interfaz web):
1. Abre `presupuesto_ui.html` en un navegador (arrastra y suelta o doble clic).
2. Carga `precios.csv` (columnas: producto,tamaño,material,precio) y `pedido.csv` (producto,cantidad,tamaño,material,nota).
3. Presiona `Generar presupuesto`. Copia con `Copiar al portapapeles`.

Cómo usar (línea de comandos):
```bash
python generate_presupuesto.py precios.csv pedido.csv [seña] [Retiro|Envío]
```

Formato recomendado CSV:
precios.csv
```
producto,tamaño,material,precio
Sticker pequeño,5x5 cm,Vinilo,30.00
```

pedido.csv
```
producto,cantidad,tamaño,material,nota
Sticker pequeño,3,5x5 cm,Vinilo,
```

Siguientes pasos posibles:
- Integrar la lógica en la UI de la aplicación (ej. Electron/React) para auto-completar el formulario `Editar trabajo`.
- Añadir validaciones y coincidencia más flexible (fuzzy matching) para nombres de producto.
