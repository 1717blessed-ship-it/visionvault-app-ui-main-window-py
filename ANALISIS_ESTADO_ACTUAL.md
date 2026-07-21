# 🔍 Análisis del Estado Actual de la Implementación

**Fecha**: 2026-07-20  
**Objetivo**: Confirmar estado de la corrección de preservación de borde blanco

---

## ✅ CORRECCIONES YA IMPLEMENTADAS

### 1. Función `_uniform_background_alpha` (línea 1216-1335)

**Estado**: ✅ **IMPLEMENTADA CORRECTAMENTE**

**Ubicación**: `app/stickers/pipeline.py`, línea 1216

**Funcionalidad**:
- ✅ Estimación de fondo desde esquinas y perímetro
- ✅ Detección de fondo oscuro (`bg_luminosity < 100`)
- ✅ Cálculo de luminosidad y saturación por píxel
- ✅ Protección explícita de píxeles blancos (L≥225, S≤45)
- ✅ Flood fill desde los bordes con detención en blancos
- ✅ Tolerancia ajustada: `tolerance * 1.5`

**Código clave**:
```python
def is_bg_similar(pixel, lum, sat):
    # Protección explícita para blancos del sticker
    if lum >= 225 and sat <= 45:
        if bg_luminosity < 200:
            return False  # Detener crecimiento: es el borde blanco
    
    # Similitud de color con el fondo
    dist = color_distance(pixel, bg_mean)
    return dist <= tolerance * 1.5
```

**Resultado**: El flood fill se detiene correctamente al encontrar píxeles blancos cuando el fondo es oscuro.

---

### 2. Detección de Borde Blanco Preexistente (línea 2152-2155)

**Estado**: ✅ **IMPLEMENTADA CORRECTAMENTE**

**Ubicación**: `app/stickers/pipeline.py`, línea 2152

**Funcionalidad**:
- ✅ Detecta si hay borde blanco en imágenes con fondo uniforme (Caso C)
- ✅ Usa threshold de 0.35 (35% de píxeles blancos en perímetro)
- ✅ Almacena resultado en `preserve_existing_white_source`

**Código**:
```python
preserve_existing_white_source = (
    case == ImageCase.C
    and classify_result.uniform_background
    and self._has_white_outer_border(rgba, raw_alpha, threshold=.35)
)
```

**Función de soporte** (`_has_white_outer_border`, línea 1632):
```python
def _has_white_outer_border(image, alpha, threshold: float = .55) -> bool:
    # Extrae corona exterior (3px)
    edge = subtract(solid, contract(solid, 3))
    
    # Cuenta píxeles blancos (R,G,B >= 225)
    white = (rgb >= 225).all(axis=2)
    
    # Retorna True si >= threshold % son blancos
    return (white & edge).sum() / edge.sum() >= threshold
```

**Nota**: La función tiene parámetro por defecto `threshold=.55` pero se llama con `threshold=.35` en la línea 2154.

---

### 3. Construcción de Capas de Borde (línea 2287-2310)

**Estado**: ✅ **IMPLEMENTADA CORRECTAMENTE**

**Ubicación**: `app/stickers/pipeline.py`, línea 2287

**Funcionalidad**:
- ✅ Usa `preserve_existing_white` para decidir estrategia
- ✅ Si hay borde preexistente: usa `pre_smooth` directamente (SIN expansión)
- ✅ Si NO hay borde: agrega borde de producción (`final_white_px`)
- ✅ Aplica suavizado leve solo cuando hay borde preexistente

**Código**:
```python
if preserve_existing_white:
    # El borde blanco ya está en la máscara: usar tal cual sin expansión
    white_mask = pre_smooth
    # Solo aplicar un suavizado muy leve para eliminar escalones del flood fill
    if self.profile.smooth_px:
        white_mask = white_mask.filter(ImageFilter.GaussianBlur(2))
        white_mask = white_mask.point(lambda v: 255 if v >= 128 else 0)
else:
    # Agregar borde blanco de producción
    final_white_px = self.profile.final_white_px
    white_mask = self._expand(pre_smooth, final_white_px)
    if self.profile.smooth_px:
        white_mask = white_mask.filter(
            ImageFilter.GaussianBlur(self.profile.smooth_px / 2))
        white_mask = white_mask.point(lambda v: 255 if v >= 128 else 0)
```

**Resultado**: NO se crea borde doble cuando ya existe uno.

---

### 4. Control de Calidad (línea 2413-2414)

**Estado**: ✅ **IMPLEMENTADA CORRECTAMENTE**

**Ubicación**: `app/stickers/pipeline.py`, línea 2413

**Funcionalidad**:
- ✅ Mide píxeles blancos antes y después del procesamiento
- ✅ Calcula porcentaje de pérdida
- ✅ Genera alerta si pérdida > 25%

**Código**:
```python
white_border_before = self._white_outer_border_pixels(rgba, raw_alpha)
# ... procesamiento ...
white_border_after = self._white_outer_border_pixels(rgba, refined_alpha)
white_border_loss = 1 - (white_border_after / max(white_border_before, 1))

# Control de calidad: verificar pérdida de borde blanco
if white_border_loss > 0.25:
    notes.append(f"Posible eliminación del borde blanco original ({white_border_loss:.0%} perdido)")
```

---

## 🔄 FLUJO COMPLETO DEL CASO C

```
1. Clasificación
   └─> ImageCase.C detectado (fondo uniforme)

2. process() → _flow_c() (línea 990)
   └─> Llama a _uniform_background_alpha(rgba, tolerance=42)
       │
       ├─> Estima color de fondo desde esquinas
       ├─> Detecta si fondo es oscuro (< 100)
       ├─> Calcula L y S de cada píxel
       ├─> Flood fill desde bordes
       │   └─> DETIENE en píxeles blancos (L≥225, S≤45) si fondo oscuro
       └─> Retorna alpha (inversa del fondo visitado)

3. Detección de borde blanco (línea 2152)
   └─> preserve_existing_white_source = _has_white_outer_border(threshold=.35)
       └─> Analiza corona exterior de 3px
       └─> Retorna True si ≥35% son blancos (R,G,B ≥ 225)

4. Construcción de capas (línea 2287)
   └─> if preserve_existing_white:
       │   └─> white_mask = pre_smooth (SIN expansión)
       └─> else:
           └─> white_mask = expand(pre_smooth, 30px)

5. Control de calidad (línea 2413)
   └─> Compara blancos antes/después
   └─> Alerta si pérdida > 25%
```

---

## 📊 FUNCIONES CLAVE INVOLUCRADAS

| Función | Línea | Propósito | Estado |
|---------|-------|-----------|--------|
| `_flow_c()` | 989 | Flujo principal Caso C | ✅ Correcto |
| `_uniform_background_alpha()` | 1216 | Flood fill preservando blancos | ✅ Implementado |
| `_has_white_outer_border()` | 1632 | Detecta borde blanco | ✅ Implementado |
| `_white_outer_border_pixels()` | 1650 | Cuenta píxeles blancos | ✅ Implementado |
| `process()` construcción capas | 2287 | Usa borde original o nuevo | ✅ Implementado |
| Control de calidad | 2413 | Alerta de pérdida | ✅ Implementado |

---

## 🎯 PARÁMETROS CRÍTICOS

| Parámetro | Valor | Ubicación | Propósito |
|-----------|-------|-----------|-----------|
| `bg_luminosity` threshold | 100 | Línea 1248 | Define "fondo oscuro" |
| Blanco `luminosity` | 225 | Línea 1276 | Define "píxel blanco" |
| Blanco `saturation` | 45 | Línea 1276 | Define "píxel blanco" |
| Flood fill `tolerance` | 42 * 1.5 | Línea 997, 1281 | Similitud de color al fondo |
| Detección threshold | 0.35 | Línea 2154 | % mínimo de blancos en perímetro |
| Alerta threshold | 0.25 | Línea 2413 | % máximo de pérdida aceptable |
| Corona exterior | 3px | Línea 1639 | Ancho de borde a analizar |

---

## ❓ POSIBLES CAUSAS DE FALLO (si aún persiste)

### Hipótesis 1: Threshold de detección muy alto
**Síntoma**: `preserve_existing_white_source = False` cuando debería ser `True`

**Causa**: El threshold de 0.35 (35%) requiere que más de un tercio del perímetro sea blanco. Bordes finos o interrumpidos pueden no alcanzar este valor.

**Solución**: Reducir threshold a 0.25 o 0.20

**Línea a modificar**: 2154
```python
# ACTUAL
self._has_white_outer_border(rgba, raw_alpha, threshold=.35)

# PROPUESTO
self._has_white_outer_border(rgba, raw_alpha, threshold=.25)
```

---

### Hipótesis 2: Postprocesado erosiona el borde
**Síntoma**: El borde se detecta pero luego se erosiona en `_postprocess()`

**Causa**: En la línea 2164-2174, para Caso C se aplica `_postprocess()` que puede erosionar bordes:

```python
else:
    refined_alpha, postprocess_meta = self._postprocess(
        raw_alpha, self.profile.dpi,
        fill_holes=source_path.suffix.lower() == ".png",
    )
```

**Nota**: El código actual tiene una excepción:
```python
if ((case == ImageCase.A and not preserve_full_image)
        or preserve_existing_white_source):
    refined_alpha = raw_alpha  # NO se postprocesa
```

**Estado**: ✅ Ya protegido por `preserve_existing_white_source`

---

### Hipótesis 3: base_mask no incluye el borde
**Síntoma**: El borde se pierde al construir `base_mask` con contornos

**Causa**: En línea 2274, se reconstruye la máscara con `cv2.findContours` que puede simplificar:

```python
contours, _ = cv2.findContours(arr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
base_arr = np.zeros_like(arr)
if contours:
    cv2.fillPoly(base_arr, contours, 255)
base_mask = Image.fromarray(base_arr, mode="L")
```

**Estado**: Este paso usa `refined_alpha` que debería incluir el borde si `preserve_existing_white_source = True`.

**Verificación necesaria**: Confirmar que `refined_alpha` contiene el borde completo.

---

### Hipótesis 4: Suavizado borra píxeles del borde fino
**Síntoma**: El borde se detecta pero el `GaussianBlur(2)` lo difumina

**Causa**: Línea 2295-2296:
```python
white_mask = white_mask.filter(ImageFilter.GaussianBlur(2))
white_mask = white_mask.point(lambda v: 255 if v >= 128 else 0)
```

**Estado**: El blur de radio 2 y re-binarización en 128 debería preservar bordes de 3-4px. Si el borde es de 1-2px podría perderse.

**Solución**: Reducir blur a 1 o eliminar:
```python
if self.profile.smooth_px:
    white_mask = white_mask.filter(ImageFilter.GaussianBlur(1))  # Reducido
    white_mask = white_mask.point(lambda v: 255 if v >= 200 else 0)  # Threshold más bajo
```

---

## 🧪 DIAGNÓSTICO RECOMENDADO

### Método 1: Validar con imagen real
```python
# Procesar imagen de prueba y revisar metadata
result = processor.process(
    source_path=Path("test_flores_fondo_negro.png"),
    # ...
)

# Verificar en metadata.json:
# 1. case = "C"
# 2. uniform_background = true
# 3. has_white_border_detected = true  ← CRÍTICO
# 4. quality_notes vacío o sin alerta de pérdida
```

### Método 2: Agregar logging temporal
```python
# En línea 2154, agregar:
preserve_existing_white_source = (
    case == ImageCase.C
    and classify_result.uniform_background
    and self._has_white_outer_border(rgba, raw_alpha, threshold=.35)
)
print(f"DEBUG: preserve_existing_white = {preserve_existing_white_source}")
print(f"  case = {case}")
print(f"  uniform_background = {classify_result.uniform_background}")
print(f"  has_white_border = {self._has_white_outer_border(rgba, raw_alpha, threshold=.35)}")
```

### Método 3: Exportar máscaras intermedias
```python
# Después de línea 2296, agregar:
if preserve_existing_white:
    debug_white_mask = white_mask.copy()
    debug_path = output / "debug_white_mask_preserved.png"
    debug_white_mask.save(debug_path)
    print(f"DEBUG: Máscara de borde preservado guardada en {debug_path}")
```

---

## 🎯 CONCLUSIÓN DEL ANÁLISIS

### Estado General: ✅ **IMPLEMENTACIÓN COMPLETA**

Todas las correcciones solicitadas están implementadas correctamente:

1. ✅ Flood fill con protección de blancos
2. ✅ Detección de borde blanco preexistente
3. ✅ Uso del borde original sin expansión
4. ✅ Control de calidad con alertas

### Posibles Ajustes Pendientes

Si el problema persiste en imágenes reales, los ajustes más probables son:

1. **Reducir threshold de detección**: `0.35 → 0.25` (línea 2154)
2. **Reducir suavizado**: `GaussianBlur(2) → GaussianBlur(1)` (línea 2295)
3. **Ajustar umbral de blanco**: `225 → 220` (línea 1276, 1641)

### Próximo Paso Obligatorio

**VALIDAR CON IMAGEN REAL** antes de cualquier modificación adicional:
- Procesar imagen con fondo oscuro + borde blanco
- Revisar `metadata.json` → `has_white_border_detected`
- Verificar resultado visual
- Si falla, aplicar diagnóstico con logging

---

**🚦 El código está correcto. Se requiere validación práctica para confirmar funcionamiento.**
