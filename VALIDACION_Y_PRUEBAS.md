# Guía de Validación y Pruebas

## Estado de la Corrección

✅ **CÓDIGO APLICADO**: Todas las correcciones están implementadas en `app/stickers/pipeline.py`  
⏳ **PENDIENTE**: Validación con imágenes reales

---

## 1. Tests Automatizados

### Ejecutar Suite de Tests

```bash
# Desde la raíz del proyecto
python tests/test_white_border_preservation.py
```

### Tests Incluidos

#### Test 1: `test_white_border_is_preserved`
**Objetivo**: Verificar que se preserve ≥75% del borde blanco original

**Qué hace**:
- Crea imagen de prueba: fondo oscuro + diseño + borde blanco
- Cuenta píxeles blancos antes del procesamiento
- Procesa con `_uniform_background_alpha`
- Cuenta píxeles blancos después
- Verifica tasa de preservación ≥ 75%

**Resultado esperado**:
```
✓ Píxeles blancos antes: 2856
✓ Píxeles blancos preservados: 2640
✓ Tasa de preservación: 92%
✓ Test PASSED
```

#### Test 2: `test_dark_background_detection`
**Objetivo**: Verificar detección correcta de fondo oscuro

**Qué hace**:
- Procesa imagen con fondo oscuro
- Verifica que se preserven píxeles blancos
- Confirma que se conserve ≥60% del borde

**Resultado esperado**:
```
✓ Se preservó píxeles blancos del borde
✓ Pérdida < 40%
✓ Test PASSED
```

#### Test 3: `test_white_pixel_not_classified_as_background`
**Objetivo**: Verificar que blancos NO se clasifiquen como fondo

**Qué hace**:
- Crea imagen simple: borde oscuro + interior blanco
- Aplica eliminación de fondo
- Verifica que la región blanca central se preserve ≥95%

**Resultado esperado**:
```
✓ Región blanca preservada: 98%
✓ Test PASSED
```

### Resultados de Éxito

Si todos los tests pasan:
```
============================================================
Test 1: Preservación del borde blanco
✓ Test PASSED

Test 2: Detección de fondo oscuro
✓ Test PASSED

Test 3: Píxeles blancos no clasificados como fondo
✓ Test PASSED

============================================================
✓ Todos los tests pasaron exitosamente
============================================================
```

---

## 2. Validación Manual con Imágenes Reales

### Preparar Imágenes de Prueba

Necesitas imágenes con estas características:

#### Imagen Tipo 1: Fondo Oscuro + Borde Blanco (CRÍTICO)
```
Características:
- Fondo: Negro o muy oscuro (L < 100)
- Diseño: Cualquier color (flores, ilustración, texto)
- Borde: Blanco continuo de 2-10mm de ancho
- Formato: JPG o PNG

Ejemplo: La imagen de flores y corazón mostrada
```

#### Imagen Tipo 2: Fondo Claro Sin Borde
```
Características:
- Fondo: Blanco o claro (L > 200)
- Diseño: Cualquier color
- Sin borde blanco preexistente
- Formato: JPG

Objetivo: Verificar que NO afecta casos normales
```

#### Imagen Tipo 3: PNG Transparente
```
Características:
- PNG con canal alpha
- Sin borde blanco en el diseño
- Formato: PNG

Objetivo: Verificar compatibilidad con Caso A
```

### Proceso de Validación

#### Paso 1: Procesar Imagen

1. Abrir la aplicación VisionVault
2. Ir a "Creador predictivo de stickers"
3. Importar imagen de prueba (Tipo 1: fondo oscuro + borde blanco)
4. Hacer clic en "Procesar cola"
5. Esperar a que termine el procesamiento

#### Paso 2: Revisar Resultado

**Vista del Resultado Final**:
- Verificar que el sticker final **incluya el borde blanco completo**
- El borde NO debe ser más grueso que el original
- El borde NO debe tener erosión visible
- El fondo oscuro debe estar completamente eliminado

**Archivos Generados** (en carpeta de salida):

1. **`mask_segmentation_raw.png`** - Máscara después de flood fill
   - ✅ Debe incluir el borde blanco
   - ✅ Solo el fondo oscuro debe estar transparente

2. **`mask_binary_intermediate.png`** - Máscara binaria limpia
   - ✅ Debe mantener el borde blanco

3. **`maestro_5_70cm.png`** - Imagen final de producción
   - ✅ **CRÍTICO**: Debe mostrar el diseño con todo su borde blanco original
   - ❌ NO debe mostrar solo las flores sin borde

4. **`control.png`** - Vista con anillo negro de registro
   - ✅ El anillo negro debe rodear el borde blanco, no el diseño interior

5. **`metadata.json`** - Información del procesamiento
   ```json
   {
     "analysis": {
       "case": "C - Fondo de color uniforme",
       "has_white_border_detected": true,  // ← Debe ser true
       ...
     },
     "quality_status": "Listo",
     "quality_notes": []  // ← Idealmente vacío
   }
   ```

#### Paso 3: Criterios de Aprobación

##### ✅ APROBADO si:

1. **Borde blanco visible**: El resultado final muestra el borde blanco completo
2. **Sin erosión**: El borde NO está más delgado que el original
3. **Sin expansión**: El borde NO está más grueso que el original
4. **Fondo eliminado**: El fondo oscuro está completamente transparente
5. **Sin alertas**: No hay alertas de pérdida de borde blanco
6. **Metadata correcta**: `has_white_border_detected: true` en metadata

##### ❌ FALLÓ si:

1. **Borde eliminado**: El resultado NO muestra el borde blanco
2. **Borde incompleto**: Se perdió más del 10% del borde original
3. **Alerta de pérdida**: Hay alerta de "Posible eliminación del borde blanco"
4. **Fondo no eliminado**: Quedan restos del fondo oscuro

---

## 3. Validación con Diferentes Escenarios

### Escenario 1: Fondo Negro + Borde Blanco Grueso (10mm)

**Imagen**: Diseño colorido con borde blanco grueso sobre fondo negro puro (#000000)

**Resultado Esperado**:
- ✅ Borde blanco completamente preservado
- ✅ Fondo negro eliminado
- ✅ Sin alertas

### Escenario 2: Fondo Gris Oscuro + Borde Blanco Fino (2mm)

**Imagen**: Diseño con borde blanco fino sobre fondo gris oscuro (#202020)

**Resultado Esperado**:
- ✅ Borde blanco fino preservado (puede haber pérdida <10% aceptable)
- ✅ Fondo gris eliminado
- ⚠️ Posible alerta si pérdida > 10%

### Escenario 3: Fondo Blanco Sin Borde (REGRESIÓN)

**Imagen**: Diseño sobre fondo blanco sin borde propio

**Resultado Esperado**:
- ✅ Fondo blanco eliminado
- ✅ Borde de producción (30px) agregado
- ✅ Sin alertas
- ✅ Funciona como antes de la corrección

### Escenario 4: PNG Transparente (REGRESIÓN)

**Imagen**: PNG con transparencia sin borde

**Resultado Esperado**:
- ✅ Transparencia respetada
- ✅ Borde de producción agregado
- ✅ Sin cambios respecto a versión anterior

### Escenario 5: Borde Blanco Interrumpido

**Imagen**: Diseño con borde blanco que se interrumpe en algunos sectores (hojas que sobresalen)

**Resultado Esperado**:
- ✅ Borde blanco preservado en los sectores donde existe
- ✅ Sectores sin borde respetados (hojas visibles)
- ⚠️ Puede haber pequeña pérdida en las interrupciones (aceptable <10%)

---

## 4. Comparación Antes/Después

### Crear Comparación Visual

```bash
# Si tienes los resultados de antes y después
# Colocarlos lado a lado para comparación
```

**Antes de la corrección**:
```
┌─────────────────┐
│                 │
│   ┌─────────┐   │
│   │ Flores  │   │  ← Sin borde blanco
│   │ Hojas   │   │
│   │ Corazón │   │
│   └─────────┘   │
│                 │
└─────────────────┘
```

**Después de la corrección**:
```
┌─────────────────────┐
│                     │
│ ┌─────────────────┐ │
│ │ Borde Blanco    │ │  ← Con borde blanco completo
│ │  ┌─────────┐    │ │
│ │  │ Flores  │    │ │
│ │  │ Hojas   │    │ │
│ │  │ Corazón │    │ │
│ │  └─────────┘    │ │
│ └─────────────────┘ │
│                     │
└─────────────────────┘
```

---

## 5. Métricas de Calidad

### Métrica 1: Preservación de Borde Blanco

```python
# Calcular desde metadata.json o durante procesamiento
preservation_rate = (white_border_after / white_border_before) * 100

# Evaluación:
# ≥ 90%: Excelente
# 75-89%: Bueno
# < 75%: Requiere revisión
```

### Métrica 2: Pérdida de Borde Blanco

```python
loss_rate = (1 - white_border_after / white_border_before) * 100

# Evaluación:
# ≤ 10%: Aceptable (pequeñas imperfecciones en bordes)
# 10-25%: Aceptable con alerta
# > 25%: Inaceptable
```

### Métrica 3: Confianza de Detección

```python
# Verificar en metadata.json
has_white_border_detected: true/false

# Si es true y el resultado es correcto → Sistema funcionando
# Si es false pero debería ser true → Revisar threshold (0.35)
```

---

## 6. Problemas Comunes y Soluciones

### Problema 1: Borde Blanco Aún Se Elimina

**Síntomas**:
- El resultado final no muestra el borde blanco
- `metadata.json` muestra `has_white_border_detected: false`

**Posibles Causas**:
1. El borde blanco cubre < 35% del perímetro
2. El borde no es suficientemente blanco (L < 225)
3. El threshold de detección es muy alto

**Solución**:
```python
# En pipeline.py, línea ~2143
# Reducir threshold de 0.35 a 0.25
self._has_white_outer_border(rgba, raw_alpha, threshold=.25)
```

### Problema 2: Borde Blanco Se Expande Demasiado

**Síntomas**:
- El borde blanco final es más grueso que el original

**Causa**:
- La lógica de `preserve_existing_white` no se está ejecutando

**Solución**:
- Verificar que la condición en línea ~2140 se cumple
- Revisar que `case == ImageCase.C`

### Problema 3: Alertas Falsas de Pérdida

**Síntomas**:
- Alerta de "Posible eliminación del borde blanco" pero el borde está bien

**Causa**:
- Pequeñas imperfecciones en el flood fill
- Threshold de alerta muy bajo (25%)

**Solución**:
```python
# En pipeline.py, línea ~2338
# Aumentar threshold de 0.25 a 0.35
if white_border_loss > 0.35:
```

---

## 7. Registro de Validación

### Plantilla de Reporte

```markdown
## Validación de Corrección: Preservación de Borde Blanco

**Fecha**: ___________
**Validador**: ___________
**Versión**: app/stickers/pipeline.py (corregido 2026-07-20)

### Tests Automatizados

- [ ] Test 1: Preservación de borde blanco - PASSED / FAILED
- [ ] Test 2: Detección de fondo oscuro - PASSED / FAILED
- [ ] Test 3: Blancos no clasificados como fondo - PASSED / FAILED

### Validación Manual

#### Imagen Tipo 1: Fondo Oscuro + Borde Blanco
- Archivo: ___________
- [ ] Borde blanco visible en resultado: SÍ / NO
- [ ] Fondo oscuro eliminado: SÍ / NO
- [ ] Sin alertas de calidad: SÍ / NO
- [ ] Tasa de preservación: ____%

#### Imagen Tipo 2: Fondo Claro Sin Borde (Regresión)
- Archivo: ___________
- [ ] Funciona como antes: SÍ / NO
- [ ] Borde de producción agregado: SÍ / NO

#### Imagen Tipo 3: PNG Transparente (Regresión)
- Archivo: ___________
- [ ] Sin cambios respecto a antes: SÍ / NO

### Resultado Final

- [ ] ✅ APROBADO: Todos los tests pasaron y validaciones manuales correctas
- [ ] ⚠️ APROBADO CON OBSERVACIONES: Funciona pero requiere ajustes menores
- [ ] ❌ RECHAZADO: Fallos críticos, requiere corrección adicional

### Observaciones

___________________________________________________________________________
___________________________________________________________________________
___________________________________________________________________________

### Firma

Validador: ___________  
Fecha: ___________
```

---

## 8. Próximos Pasos Después de la Validación

### Si Todos los Tests Pasan (✅ APROBADO)

1. **Documentar resultados** en el issue original
2. **Comunicar** a stakeholders que la corrección está validada
3. **Monitorear** resultados en uso real durante 1-2 semanas
4. **Eliminar backup** después de confirmar estabilidad

### Si Hay Problemas Menores (⚠️ APROBADO CON OBSERVACIONES)

1. **Documentar** los casos específicos con problemas
2. **Ajustar parámetros** (thresholds, tolerancias)
3. **Re-validar** con los mismos casos
4. **Aprobar** una vez corregidos los ajustes

### Si Hay Fallos Críticos (❌ RECHAZADO)

1. **Revertir** a versión anterior usando el backup
2. **Analizar** logs y metadata de casos fallidos
3. **Revisar** lógica de la corrección
4. **Aplicar** corrección adicional
5. **Re-validar** completamente

---

## Contacto y Soporte

**Documentación**:
- `RESUMEN_FINAL_CORRECCION_COMPLETA.md` - Resumen completo
- `CORRECCION_BORDE_BLANCO_PARTE_2.md` - Detalles técnicos
- `CAMBIOS_APLICADOS.md` - Registro de cambios

**Archivos de Referencia**:
- `app/stickers/pipeline.py.backup` - Versión original
- `tests/test_white_border_preservation.py` - Tests automatizados

---

**Autor**: Kiro AI  
**Fecha**: 2026-07-20  
**Versión de Este Documento**: 1.0
