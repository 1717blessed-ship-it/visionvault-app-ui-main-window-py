# Doccione Studio

Sistema local para organizar diseños, preparar stickers, gestionar pedidos, armar planchas A4 e imprimir.

## Inicio

1. Instalá las dependencias una sola vez con `python -m pip install -r requirements.txt`.
2. Abrí **Iniciar Doccione Studio.bat**.
3. Usá **Indexar carpeta** para registrar tu banco de diseños sin modificar los originales.

## Construcción automática de stickers

El botón **Crear stickers** abre una cola separada que admite pegar, elegir, arrastrar o importar una carpeta. El flujo:

- busca duplicados y similitudes locales;
- analiza transparencia, fondo, resolución y contenido;
- elige automáticamente un motor de separación;
- conserva los blancos internos y elimina solo el fondo conectado al exterior;
- genera máscara, silueta, maestro de 5,75 cm, impresión al 97,27 %, control y corte;
- permite corregir la máscara dentro de Doccione;
- guarda los trabajos pendientes para revisarlos después;
- exige aprobación antes de incorporar el maestro a la biblioteca.

Cada diseño aprobado puede tener al mismo tiempo una categoría y varias etiquetas. Los originales nunca se renombran ni se sobrescriben.

El índice y los estados se guardan localmente en `visionvault.db`; los archivos de trabajo se guardan en `work/stickers`.
