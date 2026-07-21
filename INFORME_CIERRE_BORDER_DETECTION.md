# Informe Final: Detección de Borde Blanco en Stickers

## Checkpoints

| Commit | Tag | Descripción |
|--------|-----|-------------|
| `192da19` | `sticker-border-stable-192da19` | Checkpoint inicial: detección de borde blanco con dilate-ring |
| `89bc396` | `etapa-1.6-validated` | Fix clasificación AMBIGUOUS + métricas diagnósticas |
| `529fbe0` | `etapa-2a-done` | Reconstrucción de base blanca desplazada |
| `bc809cd` | `etapa-2b-done` | Eliminación de ruido gris aislado |
| `b4614a0` | `sticker-border-final` | Validación final con 4 imágenes reales |

## Rama: `refine-sticker-cases`

## Estado de Tests

| Test suite | Resultado |
|-----------|-----------|
| `test_structural_detection.py` | **8/8** |
| `test_border_detection.py` | **8/8** |
| `test_white_base_rebuild.py` | **5/5** |
| `pytest tests -q` | **87 passed**, 1 failed (pre-existente: "embalaje" vs "packaging") |

## Tiempos de Procesamiento

| Imagen | Tiempo | Componentes | Calidad |
|--------|--------|-------------|---------|
| control_estetoscopio (600x600) | 2.67s | 4 (main=86327, 2nd=864) | Revisar |
| hoja_clara (1024x1024) | 6.21s | 1 (main=305513) | Listo |
| estetoscopio_rosa (600x600) | 2.92s | 1 (main=19562) | Revisar |
| corazon_anatomico (1200x1200) | 9.95s | 1 (main=242309) | Listo |
| **TOTAL** | **21.75s** | | |

**Overhead de 2A+2B por imagen:** < 50ms (distanceTransform + connected components en máscara alpha)

## Métricas Finales

| Imagen | Coverage | Excess | Missing | Modo |
|--------|----------|--------|---------|------|
| control | 1.000 | 0.000 | 0.000 | AMBIGUOUS |
| hoja | 1.000 | 0.000 | 0.000 | AMBIGUOUS |
| rosa | 1.000 | 0.000 | 0.000 | AMBIGUOUS |
| corazon | 1.000 | 0.000 | 0.000 | AMBIGUOUS |

## Cambios Implementados

### pipeline.py — analyze_original_border_structure
- AMBIGUOUS ahora requiere `white_in_ring >= 0.55` (antes bastaba `has_design`)
- Campos diagnósticos: perimeter_median_rgb, perimeter_luminance, perimeter_saturation, background_distance_threshold, has_design, mode_reason

### pipeline.py — Etapa 2A: _rebuild_displaced_white_base
- Trigger: `AMBIGUOUS AND coverage < 0.95 AND (missing > 0.05 OR excess > 0.10)`
- Crea design_seed desde RGB (saturation > 0.12 | luminance < 180)
- Genera base blanca via distanceTransform al diseño
- Conserva blanco existente dentro de `target_radius + tolerance`
- **Estetoscopio rosa: coverage 0.87 → 1.00**

### pipeline.py — Etapa 2B: _remove_grey_noise
- Criterios simultáneos: `area_ratio < 0.01 AND sat < 0.10 AND 170 ≤ lum ≤ 220 AND texture < 0.20 AND dark_line < 0.05`
- **Corazón: 19 → 1 componente** (18 puntos grises eliminados)
- Control preservado: 3 componentes con sat=0.13, tex=0.89, dark=0.15

## Artefactos Visuales

| Archivo | Descripción |
|---------|-------------|
| `final_validation/control_estetoscopio_clean.png` | Diseño limpio |
| `final_validation/control_estetoscopio_mask.png` | Máscara alfa |
| `final_validation/hoja_clara_clean.png` | Diseño limpio |
| `final_validation/hoja_clara_mask.png` | Máscara alfa |
| `final_validation/estetoscopio_rosa_clean.png` | Diseño limpio |
| `final_validation/estetoscopio_rosa_mask.png` | Máscara alfa |
| `final_validation/corazon_anatomico_clean.png` | Diseño limpio |
| `final_validation/corazon_anatomico_mask.png` | Máscara alfa |
| `final_validation/final_report.json` | Reporte de métricas |

## Archivos de Diagnóstico

| Archivo | Descripción |
|---------|-------------|
| `diagnose_cases.py` | Métricas de referencia (flood fill) |
| `diagnose_etapa1_5.py` | Métricas de defectos visuales |
| `diagnose_etapa1_6.py` | Métricas validadas (corregidas) |
| `diagnosis_etapa1/etapa1_6_report.json` | Reporte de diagnóstico |

## Qué NO se implementó

- Recuperación global de contenido claro
- Apertura o erosión para separar la hoja
- Eliminación automática de toda isla
- Cambios a la clasificación AMBIGUOUS_WHITE_ON_WHITE
- Cambios a umbrales ya validados
- Protección de detalle antes del flood fill
- Corte de puentes finos

## Conclusión

El pipeline pasó de aplicar correcciones generales peligrosas a tener dos tratamientos específicos, medibles y reversibles:
1. Reconstrucción de base blanca desplazada (quirúrgica, condicional)
2. Eliminación de ruido gris aislado (conservadora, con 5 criterios simultáneos)

Ambos tratamientos solo se activan bajo condiciones específicas y medibles, no afectan imágenes que no las cumplan.
