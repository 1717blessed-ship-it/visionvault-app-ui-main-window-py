# Análisis: Problema del Borde Doble en Diseños con Fondo Blanco Uniforme

**Fecha**: 2026-07-20  
**Estado**: EN PROGRESO  
**Prioridad**: ALTA

---

## Resumen Ejecutivo

**Problema**: Diseños con fondo blanco/claro uniforme Y borde blanco incorporado generan un **borde doble** después del procesamiento.

**Causa Raíz**: El flood fill actual (después de la corrección anterior) no distingue entre:
- **Borde blanco del fondo** (conectado a los bordes del canvas) → debe eliminarse
- **Borde blanco del diseño** (interior al fondo) → debe conservarse

**Situación Actual**:
- ✅ **Fondos oscuros**: Funcionan correctamente (corrección aplicada previamente)
- ❌ **Fondos blancos/claros**: Generan borde doble

---

## Contexto: Corrección Previa (Fondos Oscuros)

La corrección documentada en `RESUMEN_FINAL_CORRECCION_COMPLETA.md` solucionó:

```python
# En _uniform_background_alpha - CORRECCIÓN PREVIA
if bg_is_dark:
    if lum >= 225 and sat <= 45:
        return False  # Detener: es el borde blanco del sticker
```

**Resultado**: Diseños con **fondo oscuro + borde blanco** ahora preservan el borde correctamente.

---

## Problema Actual: Fondos Blancos/Claros

### Escenario Problemático

```
ENTRADA:
┌─────────────────────────────────────┐
│  FONDO BLANCO UNIFORME              │
│    ┌─────────────────┐              │
│    │ BORDE BLANCO    │              │
│    │ (del diseño)    │              │
│    │  ┌─────────┐    │              │
│    │  │ Diseño  │    │              │
│    │  │ Interior│    │              │
│    │  └─────────┘    │              │
│    └─────────────────┘              │
└─────────────────────────────────────┘

PROCESO ACTUAL:
1. Flood fill detecta fondo blanco en los bordes
2. Debería eliminar solo el fondo blanco exterior
3. ❌ Pero NO detiene al llegar al borde blanco del diseño
4. Resultado: borde blanco del diseño se conserva ✓
5. Pipeline agrega OTRO borde blanco de producción ✗
6. RESULTADO: BORDE DOBLE

SALIDA PROBLEMÁTICA:
┌───────────────────────────┐
│ BORDE BLANCO AGREGADO     │  ← Nuevo (30px)
│ ┌─────────────────┐       │
│ │ BORDE BLANCO    │       │  ← Original (conservado)
│ │ (original)      │       │
│ │  ┌─────────┐    │       │
│ │  │ Diseño  │    │       │
│ │  │ Interior│    │       │
│ │  └─────────┘    │       │
│ └─────────────────┘       │
└───────────────────────────┘
```

---

## Análisis de la Función Actual

### `_uniform_background_alpha` (Líneas 1216-1335)

```python
# LÓGICA ACTUAL (después de mi modificación reciente)
def is_bg_similar(pixel, lum, sat):
    dist = color_distance(pixel, bg_mean)
    
    # Para fondos blancos/claros
    if bg_is_white_or_light:
        if lum >= 200 and sat <= 50:
            # ❌ PROBLEMA: Permite atravesar blancos con tolerancia amplia
            return dist <= tolerance * 2.0  # Tolerancia más amplia
        else:
            return dist <= tolerance * 1.5
```

**Problema Identificado**:
1. Cuando el fondo es blanco (bg_luminosity >= 200)
2. El flood fill **atraviesa píxeles blancos** similares al fondo
3. **NO distingue** entre:
   - Fondo blanco conectado al canvas (eliminar)
   - Borde blanco del diseño interior (conservar)

---

## Estrategia de Solución

### Concepto Clave: Conectividad vs. Localización

**El borde blanco debe eliminarse SOLO si está conectado a los bordes del canvas**

```
CORRECTO:
┌─────────────────────────────┐
│ F F F F F F F F F F F F F F │  ← Fondo: eliminar todo
│ F F F F F F F F F F F F F F │
│ F F F ┌─────────┐ F F F F F │  ← Aquí detener
│ F F F │ B B B B │ F F F F F │  ← Borde blanco: conservar
│ F F F │ B D D B │ F F F F F │  ← Diseño: conservar
│ F F F │ B B B B │ F F F F F │
│ F F F └─────────┘ F F F F F │
│ F F F F F F F F F F F F F F │
└─────────────────────────────┘

F = Fondo blanco (eliminar)
B = Borde blanco del diseño (conservar)
D = Diseño interior (conservar)
```

### Solución Propuesta: Flood Fill con Detección de Transición

**Estrategia de Dos Fases**:

#### Fase 1: Flood Fill Conservador
- Eliminar el fondo conectado a los bordes
- **Detenerse** al encontrar cambios significativos en el gradiente/edges
- Usar detección de bordes para identificar la transición fondo → diseño

#### Fase 2: Verificación del Borde Blanco Interior
- Después del flood fill, analizar la máscara resultante
- Detectar si hay un borde blanco en el perímetro del diseño
- Ajustar el grosor del borde final de producción en consecuencia

---

## Implementación Técnica

### Modificación de `is_bg_similar`

```python
def is_bg_similar(pixel, lum, sat, nx, ny):
    """Determina si un píxel pertenece al fondo exterior.
    
    NUEVA ESTRATEGIA para fondos blancos:
    - Usar gradiente/edges para detectar transición fondo → diseño
    - Detenerse en píxeles con alto gradiente (bordes visuales)
    """
    dist = color_distance(pixel, bg_mean)
    
    if bg_is_white_or_light:
        # Para fondos blancos: verificar gradiente local
        if lum >= 200 and sat <= 50:
            # Es blanco, pero ¿es del fondo o del diseño?
            # Calcular gradiente en posición (nx, ny)
            gradient = edge_map[ny, nx]
            
            # Si hay alto gradiente, estamos en un borde visual
            if gradient > edge_threshold:
                return False  # Detener: transición visual detectada
            
            # Bajo gradiente + similar al fondo = parte del fondo
            return dist <= tolerance * 2.0
        else:
            return dist <= tolerance * 1.5
    else:
        # Para fondos oscuros (lógica existente)
        if lum >= 225 and sat <= 45:
            return False
        return dist <= tolerance * 1.5
```

### Cálculo del Mapa de Gradientes

```python
# Agregar antes del flood fill
edge_map = _compute_edge_map(rgb)
max_edge = edge_map.max() if edge_map.size else 1.0
edge_threshold = max(15.0, max_edge * 0.45)
```

---

## Plan de Implementación

### Paso 1: Modificar `_uniform_background_alpha`

**Archivos**: `app/stickers/pipeline.py` (línea ~1216)

**Cambios**:
1. ✅ Calcular mapa de gradientes ANTES del flood fill (ya existe `_compute_edge_map`)
2. ✅ Modificar `is_bg_similar` para recibir coordenadas (nx, ny)
3. ✅ Agregar verificación de gradiente para fondos blancos
4. ✅ Detener flood fill en zonas de alto gradiente

### Paso 2: Ajuste de Construcción de Capas

**Archivos**: `app/stickers/pipeline.py` (línea ~2276)

**Verificación**:
- La lógica `preserve_existing_white` debe funcionar igual
- El sistema ya detecta bordes blancos preexistentes
- **NO requiere cambios** si el flood fill funciona correctamente

### Paso 3: Tests de Regresión

**Archivos**: Crear `tests/test_white_border_white_background.py`

**Casos de Prueba**:
1. ✅ Fondo blanco + borde blanco → eliminar fondo, conservar borde
2. ✅ Fondo blanco sin borde → eliminar fondo, agregar borde de producción
3. ✅ Fondo oscuro + borde blanco → funcionamiento previo sin cambios
4. ✅ PNG transparente → funcionamiento previo sin cambios

---

## Métricas de Éxito

### Criterios de Aceptación

1. **No generar borde doble**: 
   - Diseño con fondo blanco + borde blanco → UN solo borde visible
   
2. **Conservar borde original**:
   - `white_border_loss < 0.10` (pérdida < 10%)
   
3. **No regresión en otros casos**:
   - Fondos oscuros: mantener corrección previa
   - PNG transparentes: sin cambios
   - Fotografías: sin cambios

### Verificación Visual

```
RESULTADO ESPERADO:
┌─────────────────┐
│ BORDE BLANCO    │  ← UN solo borde (el original)
│  ┌─────────┐    │
│  │ Diseño  │    │
│  │ Interior│    │
│  └─────────┘    │
└─────────────────┘

NO debe verse:
┌───────────────────────────┐
│ BORDE DOBLE ❌             │
│ ┌─────────────────┐       │
│ │ BORDE DOBLE ❌  │       │
```

---

## Riesgos y Mitigaciones

### Riesgo 1: Detección de Gradiente Demasiado Sensible

**Síntoma**: El flood fill se detiene prematuramente, dejando fondo sin eliminar

**Mitigación**:
- Umbral dinámico: `max(15.0, max_edge * 0.45)`
- Pruebas con diferentes tipos de imágenes
- Ajuste fino del umbral si es necesario

### Riesgo 2: Detección de Gradiente Insuficiente

**Síntoma**: El flood fill atraviesa el borde blanco del diseño

**Mitigación**:
- Combinar gradiente + distancia de color
- Verificar saturación (diseños suelen tener más saturación que fondos)
- Análisis de conectividad post-procesamiento

### Riesgo 3: Regresión en Casos Previos

**Síntoma**: Fondos oscuros dejan de funcionar correctamente

**Mitigación**:
- Lógica condicional clara: `if bg_is_white_or_light: ... else: ...`
- Suite de tests de regresión completa
- Verificar todos los casos de uso documentados

---

## Referencias

- **Corrección Previa**: `RESUMEN_FINAL_CORRECCION_COMPLETA.md`
- **Código Original**: `app/stickers/pipeline.py.backup`
- **Función Relacionada**: `_compute_edge_map` (ya existe)
- **Detección de Borde**: `_has_white_outer_border` (línea 1632)

---

## Estado Actual

- ✅ Análisis completado
- ✅ Causa raíz identificada
- ✅ Estrategia definida
- ⏳ **PRÓXIMO**: Implementar modificación
- ⏳ Crear tests de regresión
- ⏳ Validar con imágenes reales

---

## Resumen para Implementación

### Cambio Principal

**Archivo**: `app/stickers/pipeline.py`  
**Función**: `_uniform_background_alpha` (línea ~1268)  
**Modificación**:

```python
# ANTES
if lum >= 200 and sat <= 50:
    return dist <= tolerance * 2.0

# DESPUÉS
if lum >= 200 and sat <= 50:
    gradient = edge_map[ny, nx]
    if gradient > edge_threshold:
        return False  # Detener en borde visual
    return dist <= tolerance * 2.0
```

### Resultado Esperado

- ✅ Fondo blanco conectado a bordes → **eliminado**
- ✅ Borde blanco del diseño → **conservado**
- ✅ UN solo borde blanco en el resultado final
- ✅ Sin regresión en otros casos

---

**Análisis completado. Listo para implementación.**
