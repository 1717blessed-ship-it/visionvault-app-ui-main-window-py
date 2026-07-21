# Sistema de Línea de Tiempo Inteligente - Doccione Studio

## Resumen

El sistema de línea de tiempo inteligente transforma la gestión de pedidos en Doccione Studio, proporcionando priorización automática, estimación de tiempos y un asistente de producción que te dice qué hacer primero.

---

## 🎯 Características Principales

### 1. Línea de Tiempo Visual

Cada pedido muestra una barra de progreso con sus etapas:

```
Recibido → Esperando archivos → Diseños confirmados → 
Listo para Armado de Planchas → En Armado de Planchas → 
Listo para imprimir → Impreso → Finalizado → Entregado
```

- **Etapas completadas**: ●
- **Etapa actual**: ●
- **Etapas pendientes**: ○

### 2. Priorización Automática

El sistema calcula automáticamente la urgencia de cada pedido considerando:

- ⏰ **Tiempo hasta la entrega**
  - Fecha pasada: +100 puntos
  - Menos de 6 horas: +80 puntos
  - Menos de 24 horas: +60 puntos
  - Menos de 48 horas: +40 puntos

- 💰 **Estado de pago**
  - Pagado completo: +15 puntos
  - Seña recibida: +10 puntos
  - Pendiente: -5 puntos

- 📋 **Etapas pendientes**
  - 5+ etapas restantes: +25 puntos
  - 3-4 etapas restantes: +15 puntos

- ✏️ **Diseños sin confirmar**
  - +5 puntos por cada diseño sin confirmar (máximo 20)

- 📄 **Planchas pendientes**
  - Sin planchas armadas: +15 puntos

- 🎯 **Prioridad manual**
  - Cada punto de prioridad manual: +10 puntos

- ⚠️ **Relación tiempo disponible vs trabajo**
  - Tiempo insuficiente (ratio > 1.0): +50 puntos
  - Riesgo de atraso (ratio > 0.8): +30 puntos
  - Tiempo ajustado (ratio > 0.5): +15 puntos

#### Niveles de Prioridad

| Nivel | Rango | Color | Emoji |
|-------|-------|-------|-------|
| 🟢 **Baja** | 0-24 puntos | Verde | 🟢 |
| 🟡 **Normal** | 25-49 puntos | Amarillo | 🟡 |
| 🟠 **Alta** | 50-79 puntos | Naranja | 🟠 |
| 🔴 **Urgente** | 80+ puntos | Rojo | 🔴 |

### 3. Estimación de Tiempo

El sistema estima el tiempo de trabajo restante basándose en:

| Tarea | Tiempo estimado |
|-------|-----------------|
| Asignar un diseño | 2 minutos |
| Confirmar un diseño | 3 minutos |
| Editar en Photoshop | 15 minutos |
| Armar una plancha | 20 minutos |
| Revisar plancha | 5 minutos |
| Imprimir plancha | 5 minutos |
| Finalizar pedido | 2 minutos |
| Registrar pago | 3 minutos |

**Ejemplo:**
- Pedido con 10 diseños sin confirmar
- Sin planchas armadas
- Tiempo estimado: ~65 minutos
  - 10 diseños × 3 min = 30 min
  - 1 plancha × 20 min = 20 min
  - Impresión × 5 min = 5 min
  - Revisión y finalización = 10 min

### 4. Panel "Necesitan Atención Hoy"

Un dashboard inteligente que aparece al iniciar el programa mostrando:

- 🔴 Pedidos urgentes ordenados por prioridad
- ⏰ Tiempo restante hasta la entrega
- 🛠️ Siguiente acción recomendada
- ⏱️ Tiempo estimado para completar

**Ejemplo de tarjeta:**

```
🔴 Pedido #0158 · María González
Entrega en 6 horas

Entrega: Hoy 17:00
Trabajo estimado: 35 minutos

✓ Siguiente acción: Confirmar los diseños del cliente
   (3 minutos)

[Ir al pedido]
```

### 5. Vista de Pedidos Mejorada

La lista de pedidos ahora incluye:

| Columna | Descripción |
|---------|-------------|
| 🔴 | Emoji de prioridad |
| N.º | Número de pedido |
| Cliente | Nombre del cliente |
| **Etapa** | Etapa actual en el workflow |
| Estado | Estado manual |
| Entrega | Fecha de entrega |
| **Tiempo** | Tiempo restante (ej: "2 días 5 horas") |

Los pedidos urgentes se destacan en color rojo o naranja.

---

## 💡 Flujo de Trabajo Recomendado

### Al Iniciar el Día

1. **Abrir el dashboard de atención**
   - Botón: "⚠ Necesitan atención"
   - Muestra pedidos urgentes ordenados

2. **Trabajar de arriba hacia abajo**
   - El primer pedido es el más urgente
   - Cada tarjeta muestra la siguiente acción

3. **Seguir las recomendaciones**
   - "Confirmar diseños" → Ir al pedido y confirmar
   - "Armar plancha" → Abrir armado de planchas
   - "Imprimir" → Enviar a impresión

### Durante el Día

- La **prioridad se actualiza automáticamente**
- Los pedidos cambian de color según se acerca la entrega
- El dashboard se puede reabrir en cualquier momento

### Al Recibir un Pedido Nuevo

1. Crear el pedido con fecha de entrega
2. El sistema calcula automáticamente:
   - Prioridad según tiempo disponible
   - Etapa actual (Recibido)
   - Tiempo estimado de producción

---

## 🎨 Interfaz de Usuario

### Panel de Lista de Pedidos

```
┌─────────────────────────────────────────────────────┐
│ PEDIDOS                     [⚠ Necesitan atención]  │
│ 15 pedidos · 3 urgentes · 5 pendientes             │
├─────────────────────────────────────────────────────┤
│ 🔴│ 158│ María G.  │Diseños confirmados │Hoy 17:00│
│ 🟠│ 162│ Juan P.   │Listo para imprimir │Mañana  │
│ 🟡│ 165│ Ana L.    │Esperando archivos  │3 días  │
│ 🟢│ 170│ Carlos M. │Recibido           │5 días  │
└─────────────────────────────────────────────────────┘
```

### Panel de Pedido Individual

```
┌─────────────────────────────────────────────────────┐
│ LÍNEA DE TIEMPO                                      │
│ Diseños confirmados · 75% completado                │
│                                                      │
│ ● Recibido                                          │
│ ● Esperando archivos                                │
│ ● Diseños confirmados    ← ACTUAL                  │
│ ○ Listo para Armado de Planchas                    │
│ ○ En Armado de Planchas                            │
│ ○ Listo para imprimir                              │
│ ○ Impreso                                          │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ PRIORIDAD Y TIEMPO                                   │
│                                                      │
│ 🟠 Prioridad: Alta                                  │
│ Entrega en 6 horas                                  │
│                                                      │
│ Entrega: Hoy 18:00                                  │
│ Trabajo estimado: 35 minutos                        │
│ ⚠ Tiempo ajustado                                   │
└─────────────────────────────────────────────────────┘
```

---

## 🔧 Configuración

### Ajustar Tiempos Estimados

Los tiempos están definidos en `app/workflow/estimator.py`:

```python
TIME_ESTIMATES = {
    "assign_design": 2,          # minutos
    "confirm_design": 3,
    "prepare_photoshop": 15,
    # ...
}
```

Podés ajustarlos según tu ritmo de trabajo real.

### Cambiar Prioridad Manual

En el formulario de pedido, el campo "Prioridad" te permite forzar la urgencia:

- 0 = Sin prioridad manual
- 1-3 = Prioridad moderada (+10 a +30 puntos)
- 4+ = Prioridad crítica (+40+ puntos)

---

## 📊 Ventajas del Sistema

### Para el Operador

- ✅ **Claridad**: Siempre sabés qué hacer primero
- ✅ **Sin estrés**: El sistema te avisa antes de que sea crítico
- ✅ **Eficiencia**: No perdés tiempo decidiendo prioridades
- ✅ **Prevención**: Detecta atrasos antes de que ocurran

### Para el Negocio

- ✅ **Menos atrasos**: Alertas tempranas
- ✅ **Mejor servicio**: Cumplís fechas de entrega
- ✅ **Transparencia**: Estado visible de cada pedido
- ✅ **Trazabilidad**: Línea de tiempo completa

---

## 🚀 Próximas Mejoras

Ideas para expandir el sistema:

1. **Notificaciones push** cuando un pedido se vuelve urgente
2. **Reporte diario** por email con pedidos del día
3. **Análisis de productividad** (tiempo real vs estimado)
4. **Sugerencias de optimización** (combinar planchas, etc.)
5. **Integración con calendario** para planificar entregas

---

## 📝 Notas Técnicas

### Arquitectura

```
app/workflow/
├── timeline.py      # Etapas y progreso del workflow
├── priority.py      # Cálculo de prioridad automática
├── estimator.py     # Estimación de tiempos de trabajo
└── dashboard.py     # Panel "Necesitan atención hoy"
```

### Actualización Automática

- La prioridad se recalcula cada vez que se abre la lista de pedidos
- La línea de tiempo se actualiza al guardar cambios en un pedido
- El dashboard se regenera cada vez que se abre

### Rendimiento

- Todos los cálculos son en memoria (muy rápidos)
- No requiere conexión a internet
- Compatible con bases de datos grandes (miles de pedidos)

---

## ❓ Preguntas Frecuentes

**¿Puedo desactivar la priorización automática?**
Sí, el campo "Prioridad" manual sobrescribe el cálculo automático.

**¿Qué pasa si no pongo fecha de entrega?**
El pedido tendrá prioridad baja hasta que agregues una fecha.

**¿Puedo cambiar las etapas del workflow?**
Sí, editando `WORKFLOW_STAGES` en `app/workflow/timeline.py`.

**¿Los tiempos estimados se ajustan con la experiencia?**
Por ahora son fijos, pero es una mejora planificada para futuras versiones.

---

**Desarrollado para Doccione Studio**
Sistema de línea de tiempo inteligente v1.0
