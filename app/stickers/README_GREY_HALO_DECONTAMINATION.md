# Descontaminación de Halo Gris - Guía Rápida

## ¿Qué es el Halo Gris?

El **halo gris** es una contaminación visual que aparece alrededor del borde blanco de stickers previamente procesados. Este halo:

- 🔍 Es una sombra o resíduo del proceso de recorte anterior
- 🎨 Aparece como píxeles grises entre el borde blanco y la transparencia
- ❌ NO es parte del diseño original del sticker
- 🧹 Debe ser eliminado sin dañar el diseño

## Detección Automática

El sistema detecta automáticamente stickers con halo gris durante la clasificación:

```
Clasificación automática →
  ¿Tiene transparencia útil? ✓
  ¿Tiene píxeles grises en el borde? ✓
    → Caso B: "Sticker terminado con halo gris"
```

### Indicadores en Logs

Busca estos mensajes en los logs:

```log
INFO: Auto → Caso B (borde gris exterior detectado)
INFO: Sticker con halo gris detectado: aplicando descontaminación precisa
INFO: Descontaminación completada: 1,523 píxeles blanqueados
```

## Uso Programático

### Opción 1: Automático (Recomendado)

El sistema aplica descontaminación automáticamente durante el procesamiento:

```python
from app.stickers.pipeline import StickerProcessor

processor = StickerProcessor()
result = processor.process(
    source_path="mi_sticker.png",
    output_name="sticker_limpio"
)

# La descontaminación se aplica automáticamente si se detecta halo gris
```

### Opción 2: Manual (Casos Especiales)

Para casos especiales donde necesitas control directo:

```python
from app.stickers.grey_halo_decontamination import decontaminate_grey_halo_precise
from PIL import Image

# Cargar imagen
image = Image.open("sticker_con_halo.png").convert("RGBA")
alpha = image.getchannel("A")

# Aplicar descontaminación
cleaned = decontaminate_grey_halo_precise(
    image, 
    alpha,
    outer_band_width=8,        # Ancho de banda a inspeccionar
    grey_threshold_low=100,    # Umbral inferior de gris
    grey_threshold_high=210    # Umbral superior de gris
)

# Guardar resultado
cleaned.save("sticker_limpio.png")
```

## Parámetros de Ajuste

### `outer_band_width` (default: 8)

Controla el ancho de la banda perimetral donde se busca el halo gris.

```python
# Para halos delgados (más conservador)
outer_band_width=6

# Para halos anchos
outer_band_width=12
```

**Cuándo ajustar:**
- ⬆️ Si el halo es muy ancho y no se elimina completamente
- ⬇️ Si se están afectando detalles internos del diseño

### `grey_threshold_low` (default: 100)

Umbral inferior para detectar píxeles grises.

```python
# Para capturar grises más oscuros
grey_threshold_low=80

# Para ignorar grises oscuros (más conservador)
grey_threshold_low=120
```

**Cuándo ajustar:**
- ⬇️ Si el halo es muy oscuro y no se detecta
- ⬆️ Si se están blanqueando sombras del diseño

### `grey_threshold_high` (default: 210)

Umbral superior para detectar píxeles grises.

```python
# Para capturar grises muy claros
grey_threshold_high=220

# Para evitar tocar blancos (más conservador)
grey_threshold_high=200
```

**Cuándo ajustar:**
- ⬆️ Si el halo es muy claro y no se detecta
- ⬇️ Si se están afectando blancos del diseño

## Casos de Uso Comunes

### 1. Sticker Escaneado con Halo Gris

```python
# El sistema detecta automáticamente el halo y lo limpia
result = processor.process("sticker_escaneado.png")
```

### 2. Sticker con Puntas de Estrella

El algoritmo preserva las puntas exactas sin redondearlas:

```python
# Usar banda estrecha para máxima precisión
cleaned = decontaminate_grey_halo_precise(
    image, alpha,
    outer_band_width=6  # Más conservador
)
```

### 3. Sticker con Conexiones Finas

```python
# La banda externa no toca el interior del diseño
# Las conexiones finas se preservan automáticamente
cleaned = decontaminate_grey_halo_precise(image, alpha)
```

### 4. Diseño con Grises Intencionales

```python
# Los grises interiores se preservan automáticamente
# Solo se blanquean grises en la banda perimetral externa
cleaned = decontaminate_grey_halo_precise(image, alpha)
```

## Verificación de Resultados

### Inspección Visual

Después de la descontaminación, verifica:

1. ✅ **Halo eliminado**: No debe haber gris alrededor del borde blanco
2. ✅ **Borde preservado**: El borde blanco debe seguir intacto
3. ✅ **Geometría exacta**: Puntas, esquinas y conexiones sin cambios
4. ✅ **Diseño interior**: Grises y colores internos sin alteración

### Métricas en Logs

Revisa las métricas para confirmar operación correcta:

```log
INFO: Ratio de píxeles blancos: 45%           # Debe ser >10% para stickers con borde blanco
INFO: Banda externa definida: 3,247 píxeles   # Tamaño razonable de la banda
INFO: Píxeles grises en banda: 47%            # Confirma presencia de halo
INFO: Descontaminación completada: 1,523 px   # Cantidad blanqueada
```

## Solución de Problemas

### Problema: El halo no se elimina completamente

**Causa probable:** Halo muy ancho o muy claro

**Solución:**
```python
cleaned = decontaminate_grey_halo_precise(
    image, alpha,
    outer_band_width=12,          # Aumentar banda
    grey_threshold_high=220       # Capturar grises más claros
)
```

### Problema: Se están blanqueando partes del diseño

**Causa probable:** Parámetros muy agresivos

**Solución:**
```python
cleaned = decontaminate_grey_halo_precise(
    image, alpha,
    outer_band_width=6,           # Reducir banda
    grey_threshold_low=120        # Más conservador con grises oscuros
)
```

### Problema: Las puntas se redondean

**Causa probable:** Esto NO debería ocurrir con el algoritmo nuevo

**Verificación:**
1. Confirmar que se está usando `decontaminate_grey_halo_precise()` y no `_whiten_neutral_outer_halo()`
2. Revisar logs para confirmar "aplicando descontaminación precisa"
3. Si el problema persiste, reportar con imagen de ejemplo

### Problema: No se detecta halo automáticamente

**Causa probable:** Ratio de gris en banda perimetral < 20%

**Solución manual:**
```python
# Aplicar descontaminación manualmente
from app.stickers.grey_halo_decontamination import decontaminate_grey_halo_precise

cleaned = decontaminate_grey_halo_precise(
    image, alpha,
    outer_band_width=10,          # Banda más ancha para captura
    grey_threshold_low=90         # Umbral más bajo
)
```

## Demostración

Ejecuta el script de demostración para ver ejemplos visuales:

```bash
python examples/demo_grey_halo_decontamination.py
```

Esto generará:
- Imágenes de ejemplo con halo gris
- Comparaciones antes/después lado a lado
- Resultados limpios

## Tests

Ejecuta los tests unitarios:

```bash
python -m pytest tests/test_grey_halo_decontamination.py -v
```

Tests incluidos:
- ✅ Sticker con halo gris básico
- ✅ Sticker sin halo (no debe cambiar)
- ✅ Forma de estrella (preservar puntas)
- ✅ Imagen vacía (manejo de edge case)
- ✅ Parámetros personalizados

## Documentación Completa

Para detalles técnicos completos sobre el algoritmo, consulta:

📚 **[docs/grey_halo_decontamination.md](../../docs/grey_halo_decontamination.md)**

Incluye:
- Arquitectura del sistema
- Explicación detallada del algoritmo de 5 pasos
- Comparación con método anterior
- Mejoras futuras

## Soporte

Si encuentras problemas o tienes preguntas:

1. 🔍 Revisa los logs para métricas de detección
2. 📖 Consulta la documentación completa
3. 🧪 Ejecuta los tests para confirmar funcionamiento
4. 🎨 Usa el script de demostración para ejemplos visuales

---

**Versión:** 1.0  
**Última actualización:** 2026
