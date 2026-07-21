# Corrección Parte 2: Preservación del Borde Blanco en la Capa Final

## Problema Identificado

Aunque la **Parte 1** corrigió la eliminación del fondo para preservar el borde blanco durante el flood fill, el resultado final **aún mostraba el sticker sin borde blanco** porque:

1. ✅ El flood fill YA preservaba el borde blanco correctamente
2. ❌ Pero la construcción de la capa final establecía `final_white_px = 0`
3. ❌ Esto eliminaba completamente el borde blanco de la máscara final
4. ❌ El resultado: sticker recortado a la silueta del diseño sin su borde

## Evidencia Visual

La imagen de prueba mostraba:
- **Entrada**: Flores, hojas y corazón con borde blanco sobre fondo negro
- **Resultado anterior**: Sticker recortado directamente a las flores (sin borde blanco)
- **Esperado**: Sticker con todo el borde blanco original visible

## Cambios Aplicados

### Ubicación
**Archivo**: `app/stickers/pipeline.py`  
**Sección**: Construcción de capas de borde (línea ~2276)

### Antes (INCORRECTO)

```python
preserve_existing_white = preserve_existing_white_source
final_white_px = 0 if preserve_existing_white else self.profile.final_white_px
# ...
white_mask = self._expand(pre_smooth, final_white_px)  # ← Expansión de 0 píxeles
```

**Problema**: `final_white_px = 0` hace que no se agregue ningún borde, eliminando el borde blanco original.

### Después (CORRECTO)

```python
preserve_existing_white = preserve_existing_white_source

# Si hay borde blanco preexistente, usar la máscara tal cual (ya incluye el borde)
# Si no, agregar el borde blanco de producción
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

black_mask = self._expand(white_mask, control_black_px)
```

**Solución**: 
- Cuando `preserve_existing_white = True`: Usa `pre_smooth` directamente (que ya incluye el borde blanco original)
- Solo aplica suavizado leve para eliminar escalones del flood fill
- NO expande ni reduce la máscara

## Control de Calidad Adicional

Se agregó verificación de pérdida de borde blanco:

```python
# Control de calidad: verificar pérdida de borde blanco
if white_border_loss > 0.25:
    notes.append(f"Posible eliminación del borde blanco original ({white_border_loss:.0%} perdido)")
```

Esto alertará si se pierde más del 25% del borde blanco original durante el procesamiento.

## Lógica Completa del Flujo

### 1. Detección de Borde Blanco Preexistente

```python
preserve_existing_white_source = (
    case == ImageCase.C                           # Fondo uniforme
    and classify_result.uniform_background
    and self._has_white_outer_border(rgba, raw_alpha, threshold=.35)  # ≥35% píxeles blancos en el borde
)
```

### 2. Preservación Durante Flood Fill

El método `_uniform_background_alpha` ahora:
- Calcula luminosidad y saturación por píxel
- Detecta si el fondo es oscuro (L < 100)
- Detiene el flood fill al encontrar blancos (L ≥ 225, S ≤ 45)
- NO clasifica blancos como fondo

### 3. Omisión del Postprocesado Geométrico

```python
if preserve_existing_white_source:
    refined_alpha = raw_alpha  # Usar tal cual, sin erosión ni morfología
```

### 4. Uso del Borde Original en la Capa Final

```python
if preserve_existing_white:
    white_mask = pre_smooth  # Ya incluye el borde blanco original
    # Solo suavizado leve
else:
    white_mask = self._expand(pre_smooth, final_white_px)  # Agregar borde de producción
```

## Casos de Uso

### ✅ Caso 1: Fondo Oscuro + Borde Blanco Original

**Entrada**: Flores y corazón con borde blanco sobre fondo negro  
**Procesamiento**:
1. Detecta fondo oscuro (L < 100)
2. Detecta borde blanco (≥35% píxeles blancos en perímetro)
3. Flood fill se detiene en los blancos
4. Omite postprocesado geométrico
5. Usa la máscara con borde original directamente
6. **Resultado**: Sticker con todo el borde blanco visible

### ✅ Caso 2: Fondo Claro Sin Borde Blanco

**Entrada**: Diseño sobre fondo blanco/claro sin borde propio  
**Procesamiento**:
1. No detecta borde blanco preexistente
2. Aplica postprocesado geométrico normal
3. Agrega borde blanco de producción (30px)
4. **Resultado**: Sticker con borde blanco de producción

### ✅ Caso 3: PNG Transparente

**Entrada**: PNG con transparencia sin borde  
**Procesamiento**:
1. Caso A (PNG transparente)
2. Usa canal alpha existente
3. Agrega borde blanco de producción
4. **Resultado**: Sticker con borde blanco de producción

## Parámetros Clave

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `threshold` | 0.35 | % mínimo de píxeles blancos en borde para detectar borde existente |
| `luminosity_threshold` | 225 | Luminosidad mínima para considerar un píxel como blanco |
| `saturation_threshold` | 45 | Saturación máxima para blancos (colores neutros) |
| `bg_dark_threshold` | 100 | Luminosidad máxima para considerar fondo oscuro |
| `smooth_px` | 2 | Suavizado leve para eliminar escalones del flood fill |
| `white_border_loss_alert` | 0.25 | Umbral para alerta de pérdida de borde blanco (25%) |

## Verificación

### Visual
1. Procesar imagen con fondo oscuro + borde blanco
2. Verificar que el resultado final **incluya todo el borde blanco original**
3. El borde NO debe ser más grueso que el original
4. El borde NO debe tener erosión visible

### Métricas
```python
white_border_before = self._white_outer_border_pixels(rgba, raw_alpha)
white_border_after = self._white_outer_border_pixels(rgba, refined_alpha)
white_border_loss = 1 - (white_border_after / max(white_border_before, 1))

# Esperado: white_border_loss < 0.10 (pérdida < 10%)
```

## Archivos Modificados

1. **app/stickers/pipeline.py** (líneas ~2276-2295)
   - Construcción de capas de borde con preservación condicional
   
2. **app/stickers/pipeline.py** (líneas ~2335-2340)
   - Control de calidad con alerta de pérdida de borde blanco

## Impacto

### ✅ Mejorado
- **Imágenes con fondo oscuro + borde blanco**: Ahora preservan completamente el borde original
- **Stickers con silueta blanca sobre negro**: Mantienen toda la banda blanca visible
- **Control de calidad**: Detecta y alerta pérdida de borde blanco

### ✅ Sin Cambios
- **PNG transparentes**: Siguen funcionando igual
- **Stickers terminados**: Sin cambios
- **Fotografías**: Sin cambios
- **Fondos claros**: Sin cambios

## Comparación: Antes vs Después

### Antes (Ambas Partes)

```
Entrada: [Fondo Negro][Borde Blanco][Flores Rosadas][Hojas Verdes][Corazón]
                            ↓
Flood Fill: Elimina [Fondo Negro] y [Borde Blanco]  ← ERROR
                            ↓
Capa Final: [Flores][Hojas][Corazón] (sin borde)  ← INCORRECTO
```

### Después de Parte 1

```
Entrada: [Fondo Negro][Borde Blanco][Flores Rosadas][Hojas Verdes][Corazón]
                            ↓
Flood Fill: Elimina solo [Fondo Negro], preserva [Borde Blanco]  ← CORRECTO
                            ↓
Capa Final: final_white_px = 0 → sin borde  ← ERROR
                            ↓
Resultado: [Flores][Hojas][Corazón] (sin borde)  ← INCORRECTO
```

### Después de Parte 2 (COMPLETO)

```
Entrada: [Fondo Negro][Borde Blanco][Flores Rosadas][Hojas Verdes][Corazón]
                            ↓
Flood Fill: Elimina solo [Fondo Negro], preserva [Borde Blanco]  ← CORRECTO
                            ↓
Capa Final: Usa máscara con borde original  ← CORRECTO
                            ↓
Resultado: [Borde Blanco][Flores][Hojas][Corazón]  ← CORRECTO ✓
```

## Resumen

La corrección completa requiere **dos cambios coordinados**:

1. **Parte 1**: Modificar `_uniform_background_alpha` para NO eliminar blancos durante flood fill
2. **Parte 2**: Modificar construcción de capas finales para NO establecer `final_white_px = 0`

Ambas partes son necesarias para que el borde blanco original se preserve correctamente en el resultado final.

---

**Estado**: ✅ CORRECCIÓN COMPLETA APLICADA  
**Fecha**: 2026-07-20  
**Autor**: Kiro AI
