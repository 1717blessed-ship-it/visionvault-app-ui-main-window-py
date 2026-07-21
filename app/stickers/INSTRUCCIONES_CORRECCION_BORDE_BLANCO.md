# Corrección del Procesamiento de Imágenes con Fondo Oscuro y Borde Blanco

## Problema Actual

En el resultado actual se elimina correctamente el fondo oscuro, pero también se borra el borde blanco original del diseño. La máscara final queda ajustada directamente a flores, hojas y corazón, cuando debería conservar toda la silueta blanca visible en la imagen de entrada.

## Cambios Requeridos

### 1. Archivo: `app/stickers/pipeline.py`

**Ubicación**: Línea ~1218, método `_uniform_background_alpha` de la clase `StickerProcessor`

**Acción**: Reemplazar el método completo con la versión corregida que está en `pipeline_fix.py`

### 2. Cambios Clave en la Lógica

El nuevo método implementa:

#### A. Estimación del color del fondo
```python
# Calcular el color promedio del borde exterior
bg_mean = tuple(int(bg_arr.mean(axis=0)[i]) for i in range(3))
bg_luminosity = 0.299 * bg_mean[0] + 0.587 * bg_mean[1] + 0.114 * bg_mean[2]
bg_is_dark = bg_luminosity < 100
```

#### B. Cálculo de luminosidad y saturación por píxel
```python
luminosity = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.float32)

# Saturación HSV simplificada
rgb_max = rgb.max(axis=2).astype(np.float32)
rgb_min = rgb.min(axis=2).astype(np.float32)
saturation = np.zeros_like(luminosity)
nonzero = rgb_max > 0
saturation[nonzero] = ((rgb_max[nonzero] - rgb_min[nonzero]) / rgb_max[nonzero]) * 255.0
```

#### C. Protección Explícita para Blancos del Sticker
```python
def is_bg_similar(pixel, lum, sat):
    """Determina si un píxel pertenece al fondo exterior.
    
    Condiciones:
    - Debe ser similar al color de fondo detectado (distancia <= tolerance*1.5)
    - Si el fondo es oscuro y el píxel es blanco claro (L>=225, S<=45):
      NO es fondo, es el borde blanco del sticker
    """
    # Protección explícita para blancos del sticker
    if lum >= 225 and sat <= 45:
        # Es un blanco puro/casi puro → puede ser el borde blanco
        # Solo considerarlo fondo si el fondo también es blanco
        if bg_luminosity < 200:
            return False  # Detener crecimiento: es el borde blanco
    
    # Similitud de color con el fondo
    dist = color_distance(pixel, bg_mean)
    return dist <= tolerance * 1.5
```

#### D. Flood Fill con Detención en Blancos
El flood fill ahora evalúa luminosidad y saturación de cada píxel:

```python
while queue:
    x, y = queue.popleft()
    for dx, dy in neighbors:
        nx, ny = x + dx, y + dy
        if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx]:
            pixel = tuple(rgb[ny, nx])
            lum = luminosity[ny, nx]
            sat = saturation[ny, nx]
            
            if is_bg_similar(pixel, lum, sat):
                visited[ny, nx] = True
                queue.append((nx, ny))
```

### 3. Principios del Cambio

#### ✅ HACER:
1. **Estimar el color del fondo exclusivamente desde las cuatro esquinas y el marco exterior**
2. **Ejecutar flood fill desde los límites de la imagen**
3. **Eliminar solamente los píxeles conectados al exterior cuya distancia de color respecto del fondo oscuro sea suficientemente baja**
4. **La máscara inicial del sticker debe ser la inversa del fondo exterior eliminado**
5. **Detener obligatoriamente el flood fill al llegar a píxeles claros (L >= 225, S <= 45)**
6. **Conservar la banda blanca continua que rodea el diseño**

#### ❌ NO HACER:
1. **NO clasificar los píxeles blancos como fondo por su baja saturación**
2. **NO aplicar erosión sobre la máscara final cuando se haya detectado un borde blanco preexistente**
3. **NO generar un nuevo borde blanco grueso; utilizar el borde original como silueta final**

### 4. Condición de Fondo Correcta

La condición ahora se basa en similitud con el **fondo oscuro**, no en que el píxel sea poco saturado:

```python
es_fondo_exterior = (
    conectado_al_limite
    and delta_e(pixel, color_fondo) <= tolerancia_fondo
)
```

Con protección explícita para blancos:

```python
es_blanco_del_sticker = (
    luminosidad >= 225
    and saturacion <= 45
    and no_es_similar_al_fondo
)

if es_blanco_del_sticker:
    detener_crecimiento = True
    conservar_en_mascara = True
```

### 5. Control de Calidad Adicional

Agregar verificación de pérdida de borde blanco en el método `process()` (alrededor de la línea 2500):

```python
# Control de calidad: verificar pérdida del borde blanco
white_border_before = self._white_outer_border_pixels(rgba, raw_alpha)
# ... procesamiento ...
white_border_after = self._white_outer_border_pixels(rgba, refined_alpha)
perdida_borde_blanco = 1 - (white_border_after / max(white_border_before, 1))

if perdida_borde_blanco > 0.25:
    notes.append("Posible eliminación del borde blanco original")
    quality_confidence *= 0.65  # Reducir confianza si se pierde >25% del borde
```

## Archivos a Revisar

1. **`app/stickers/pipeline.py`** - Archivo principal con la función a corregir
2. **`app/stickers/pipeline_fix.py`** - Referencia con la función corregida
3. **Este archivo** - Instrucciones completas de la corrección

## Verificación

Después de aplicar el cambio, verificar con:
- Imágenes con fondo oscuro y borde blanco (como el ejemplo de flores y corazón)
- El borde blanco original debe conservarse completamente
- La máscara final debe incluir tanto el diseño como su borde blanco
- El flujo no debe aplicar erosión adicional sobre el borde blanco detectado

## Nota Importante

El cambio preserva la lógica del Flujo C (fondo uniforme) y solo modifica el método `_uniform_background_alpha` para detectar y preservar bordes blancos existentes correctamente.
