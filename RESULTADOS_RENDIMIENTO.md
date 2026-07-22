# Resultados de Medición - Rendimiento en Uso Normal

Fecha: 2026-07-22 01:44
Iteraciones por operación: 3

## Tabla de Resultados

| Operación | Media (ms) | Mediana (ms) | Min (ms) | Max (ms) | Desv (ms) |
|-----------|------------|--------------|----------|----------|----------|
| import_tkinter | 12.09 | 0.00 | 0.00 | 36.25 | 20.93 |
| import_pillow | 16.80 | 0.00 | 0.00 | 50.39 | 29.09 |
| db_init | 6.68 | 4.27 | 4.05 | 11.73 | 4.38 |
| order_summaries | 4.67 | 4.49 | 4.14 | 5.39 | 0.65 |
| orders | 4.71 | 4.56 | 4.26 | 5.32 | 0.55 |
| all_images | 26.81 | 26.75 | 25.57 | 28.11 | 1.27 |
| search_visual | 67.74 | 67.80 | 67.10 | 68.32 | 0.61 |
| search_text | 34.70 | 34.47 | 33.83 | 35.79 | 1.00 |
| pending_orders | 4.50 | 4.29 | 4.24 | 4.97 | 0.41 |
| order_events | 6.04 | 4.98 | 4.81 | 8.33 | 1.98 |
| recent_events | 4.23 | 4.30 | 4.09 | 4.31 | 0.13 |
| order_designs | 29.27 | 29.21 | 29.08 | 29.52 | 0.22 |
| visual_search_images | 102.71 | 102.77 | 99.39 | 105.99 | 3.30 |
| thumbnail_creation | 8.56 | 5.49 | 4.90 | 15.28 | 5.83 |
| image_open_close | 0.72 | 0.62 | 0.58 | 0.97 | 0.21 |
| folder_scan | 0.00 | - | - | - | - |

## Detalle por Iteración

### import_tkinter
- Iteración 1: 36.25 ms
- Iteración 2: 0.00 ms
- Iteración 3: 0.00 ms

### import_pillow
- Iteración 1: 50.39 ms
- Iteración 2: 0.00 ms
- Iteración 3: 0.00 ms

### db_init
- Iteración 1: 11.73 ms
- Iteración 2: 4.27 ms
- Iteración 3: 4.05 ms

### order_summaries
- Iteración 1: 4.49 ms
- Iteración 2: 5.39 ms
- Iteración 3: 4.14 ms

### orders
- Iteración 1: 5.32 ms
- Iteración 2: 4.56 ms
- Iteración 3: 4.26 ms

### all_images
- Iteración 1: 26.75 ms
- Iteración 2: 25.57 ms
- Iteración 3: 28.11 ms

### search_visual
- Iteración 1: 68.32 ms
- Iteración 2: 67.10 ms
- Iteración 3: 67.80 ms

### search_text
- Iteración 1: 33.83 ms
- Iteración 2: 34.47 ms
- Iteración 3: 35.79 ms

### pending_orders
- Iteración 1: 4.97 ms
- Iteración 2: 4.24 ms
- Iteración 3: 4.29 ms

### order_events
- Iteración 1: 4.98 ms
- Iteración 2: 4.81 ms
- Iteración 3: 8.33 ms

### recent_events
- Iteración 1: 4.31 ms
- Iteración 2: 4.30 ms
- Iteración 3: 4.09 ms

### order_designs
- Iteración 1: 29.21 ms
- Iteración 2: 29.08 ms
- Iteración 3: 29.52 ms

### visual_search_images
- Iteración 1: 105.99 ms
- Iteración 2: 102.77 ms
- Iteración 3: 99.39 ms

### thumbnail_creation
- Iteración 1: 15.28 ms
- Iteración 2: 4.90 ms
- Iteración 3: 5.49 ms

### image_open_close
- Iteración 1: 0.97 ms
- Iteración 2: 0.62 ms
- Iteración 3: 0.58 ms

## Resumen

- **Tiempo total DB (medición secuencial):** 285.39 ms
- **Tiempo total imagen:** 9.28 ms
- **DB init:** 6.68 ms
- **Folder scan:** 0.00 ms (0 archivos)
