# Descontaminación de Halo Gris en Stickers

## Descripción General

Este módulo implementa un sistema especializado para eliminar halos grises perimetrales en stickers que ya han sido procesados previamente. El algoritmo está diseñado específicamente para preservar la integridad del borde blanco verdadero del sticker y la geometría exacta del diseño, incluyendo elementos delicados como estrellas, puntas, y conexiones finas.

## Problema que Resuelve

Cuando un sticker previamente procesado se vuelve a procesar o se escanea, a menudo aparece un **halo gris** alrededor del borde blanco del sticker. Este halo es una contaminación que:

- Proviene del proceso de recorte o digitalización anterior
- Se encuentra entre el borde blanco verdadero y la transparencia externa
- No es parte del diseño original del sticker
- Debe ser eliminado sin afectar el diseño

### Desafío Principal

El desafío técnico más importante es **distinguir entre**:

1. **Halo gris contaminante**: Píxeles grises NO deseados que rodean el borde blanco
2. **Borde blanco verdadero**: Parte integral del sticker que DEBE preservarse
3. **Elementos grises del diseño**: Grises internos que son parte del arte original

Además, el proceso debe **preservar la geometría exacta**:
- ❌ No redondear esquinas puntiagudas
- ❌ No erosionar puntas de estrellas
- ❌ No romper conexiones finas
- ❌ No suavizar bordes rectos

## Arquitectura de la Solución

### 1. Detección Automática

El sistema de clasificación (`pipeline.py`) detecta automáticamente stickers con halo gris:

```python
# En el método classify()
if useful_alpha and has_grey_border:
    case = ImageCase.B
    reasons.append("Auto → Caso B (borde gris exterior detectado)")
```

**Criterios de detección:**
- Imagen con transparencia útil (`useful_alpha`)
- Presencia de píxeles grises neutros (R≈G≈B) en la banda perimetral
- Grises conectados al borde de la máscara opaca (≥20% de la banda interna)

### 2. Routing Inteligente

Un dispatcher selecciona el algoritmo apropiado:

```python
@staticmethod
def _decontaminate_halo_dispatcher(image, alpha, case, classify_result):
    if case == ImageCase.B and classify_result.has_grey_border:
        # Usar descontaminación precisa
        return decontaminate_grey_halo_precise(image, alpha, ...)
    else:
        # Usar método general
        return _whiten_neutral_outer_halo(image, alpha)
```

### 3. Algoritmo de Descontaminación Precisa

La función `decontaminate_grey_halo_precise()` implementa un proceso de 5 pasos:

#### Paso 1: Detección del Borde Blanco Verdadero
```python
white_pixels = (opaque_mask > 0) & (r > 210) & (g > 210) & (b > 210)
```
- Identifica píxeles con R,G,B > 210 (casi blancos)
- Solo dentro de la región opaca del sticker

#### Paso 2: Definición de la Banda Externa
```python
# Expansión suave hacia afuera (captura el halo)
opaque_expanded = cv2.dilate(opaque_mask * 255, kernel_outer, iterations=1)

# Contracción hacia adentro (límite interno)
opaque_contracted = cv2.erode(opaque_mask * 255, kernel_inner, iterations=1)

# La banda externa es la diferencia
outer_band = (opaque_expanded > 127) & (opaque_contracted == 0)
```

**Características clave:**
- Kernel pequeño (3x3 o 5x5) para preservar detalles finos
- Erosión conservadora para no perder puntas
- Banda estrecha (8 píxeles por defecto)

#### Paso 3: Detección de Píxeles Grises Neutros
```python
is_neutral = (
    (channel_diff_rg <= 20) & 
    (channel_diff_gb <= 20) & 
    (channel_diff_rb <= 20)
)
in_grey_range = (r >= grey_threshold_low) & (r <= grey_threshold_high)
grey_halo_pixels = (outer_band > 0) & is_neutral & in_grey_range
```

**Criterios de gris neutral:**
- Diferencia entre canales R, G, B ≤ 20 (colores no saturados)
- Luminosidad en rango [100, 210] por defecto (ni negro ni blanco puro)
- **Solo** dentro de la banda externa (no toca el interior)

#### Paso 4: Verificación de Seguridad
```python
if grey_ratio < 0.05:
    # No hay suficiente gris para justificar intervención
    return image.convert("RGBA")
```

Si menos del 5% de la banda es gris, probablemente no hay halo real.

#### Paso 5: Blanqueo Selectivo
```python
rgba[grey_halo_pixels, :3] = 255  # Blanquear RGB, preservar alpha
```

**Clave:** Esta operación es **pixel-perfect** y no aplica ninguna operación morfológica que pueda redondear o suavizar la forma.

## Ventajas del Algoritmo

### 1. Preservación de Geometría
- ✅ No aplica dilatación/erosión sobre la forma final
- ✅ Kernel de tamaño mínimo (3x3-5x5) para detección
- ✅ Operación de blanqueo directa (no morfológica)

### 2. Precisión en Detección
- ✅ Banda externa estrecha (solo donde puede estar el halo)
- ✅ Detección de neutralidad de color (evita confundir con diseño)
- ✅ Umbral de ratio mínimo (evita falsos positivos)

### 3. Seguridad
- ✅ No toca el interior del diseño
- ✅ Fallback al método general en caso de error
- ✅ Logging detallado para diagnóstico

## Parámetros Configurables

```python
decontaminate_grey_halo_precise(
    image,                      # PIL Image RGBA
    alpha,                      # PIL Image L (canal alfa)
    outer_band_width=8,         # Ancho de banda externa en píxeles
    grey_threshold_low=100,     # Umbral inferior de gris
    grey_threshold_high=210     # Umbral superior de gris
)
```

### Guía de Ajuste

**`outer_band_width` (default: 8)**
- ⬆️ Aumentar si el halo es muy ancho
- ⬇️ Reducir para preservar más detalles finos
- Rango recomendado: 6-12 píxeles

**`grey_threshold_low` (default: 100)**
- ⬆️ Aumentar para ignorar grises más oscuros
- ⬇️ Reducir para capturar halos muy oscuros
- Rango recomendado: 80-120

**`grey_threshold_high` (default: 210)**
- ⬆️ Aumentar para capturar grises muy claros
- ⬇️ Reducir para evitar tocar blancos verdaderos
- Rango recomendado: 200-220

## Integración en el Pipeline

El sistema se integra automáticamente en el flujo de procesamiento:

```
Entrada: Imagen RGBA
    ↓
Clasificación (classify)
    ↓
¿Tiene halo gris? (has_grey_border)
    ↓
SI: decontaminate_grey_halo_precise()
    ↓
NO: _whiten_neutral_outer_halo() (método general)
    ↓
Salida: Imagen limpia
```

## Casos de Uso

### Caso 1: Sticker con Estrella
**Problema:** Las puntas de la estrella se redondean o erosionan

**Solución:** 
- Kernel mínimo (3x3) en detección de banda
- Sin morfología sobre resultado final
- Blanqueo pixel-perfect

### Caso 2: Sticker con Conexiones Finas
**Problema:** Líneas delgadas se rompen o adelgazan

**Solución:**
- Banda externa estrecha (8px)
- Erosión conservadora para límite interno
- Detección solo en periferia

### Caso 3: Diseño con Grises Internos
**Problema:** Grises del diseño se blanquean incorrectamente

**Solución:**
- Detección SOLO en banda externa
- Interior completamente protegido
- Verificación de neutralidad de color

## Métricas de Logging

El sistema registra métricas detalladas para diagnóstico:

```
INFO: Iniciando descontaminación de halo gris: outer_band_width=8, grey_range=[100, 210]
INFO: Ratio de píxeles blancos en región opaca: 45%
INFO: Banda externa definida: 3,247 píxeles
INFO: Píxeles grises detectados en banda: 1,523 (46.9% de la banda)
INFO: Descontaminación completada: 1,523 píxeles blanqueados
```

## Testing

Se incluye suite completa de tests unitarios:

```python
# tests/test_grey_halo_decontamination.py
- test_sticker_with_grey_halo()          # Caso básico con halo
- test_sticker_without_grey_halo()       # Sin halo (no debe cambiar)
- test_sticker_with_star_shape()         # Preservar puntas
- test_empty_image()                     # Imagen vacía
- test_grey_threshold_parameters()       # Parámetros personalizados
```

Ejecutar tests:
```bash
python -m pytest tests/test_grey_halo_decontamination.py -v
```

## Comparación con Método Anterior

| Aspecto | Método Anterior | Método Nuevo |
|---------|----------------|--------------|
| **Algoritmo** | `_whiten_neutral_outer_halo()` | `decontaminate_grey_halo_precise()` |
| **Kernel** | 12px (más agresivo) | 3-8px (conservador) |
| **Banda** | Contracción simple | Expansión + Contracción |
| **Detección** | Gris genérico | Gris neutral específico |
| **Seguridad** | Media | Alta (ratio mínimo) |
| **Geometría** | Puede redondear | Preserva exacta |
| **Logging** | Mínimo | Detallado |

## Archivos Relacionados

- **Implementación:** `app/stickers/grey_halo_decontamination.py`
- **Integración:** `app/stickers/pipeline.py` (línea ~4200, ~6110)
- **Tests:** `tests/test_grey_halo_decontamination.py`
- **Modelos:** `app/stickers/models.py` (ClassifyResult.has_grey_border)

## Dependencias

- **numpy**: Operaciones de array para procesamiento eficiente
- **opencv-python (cv2)**: Operaciones morfológicas (dilate, erode)
- **Pillow (PIL)**: Manipulación de imágenes

## Futuras Mejoras

Posibles extensiones del algoritmo:

1. **Detección adaptativa de banda:** Ajustar `outer_band_width` según el tamaño de la imagen
2. **Análisis de gradiente:** Detectar transiciones suaves gris→blanco
3. **Múltiples pasadas:** Aplicar descontaminación en capas si el halo es muy ancho
4. **Heurísticas de forma:** Usar contornos para validar geometría esperada
5. **Machine Learning:** Entrenar clasificador para distinguir halo de diseño

## Licencia

Este módulo es parte de VisionVault y sigue la misma licencia del proyecto principal.

---

**Autor:** Implementación especializada para descontaminación precisa de halos grises  
**Fecha:** 2026  
**Versión:** 1.0
