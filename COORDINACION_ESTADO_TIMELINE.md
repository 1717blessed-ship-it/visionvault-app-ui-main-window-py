Sí, y creo que fue una de las mejores ideas para el flujo de trabajo de Doccione Studio. La idea era que cada pedido tenga una línea de tiempo inteligente, para que siempre sepas qué trabajo hacer primero.
Línea de tiempo del pedido
Cada pedido tendría una barra de progreso visible:

text

Recibido  
────●──────────────  
Diseños  
────────●──────────  
Armado de Plancha  
────────────●──────  
Impresión  
────────────────●──  
Finalizado  
──────────────────●
La etapa actual se resalta y las anteriores quedan marcadas como completadas.

Fecha de entrega
Cada pedido guarda:

Fecha de creación.
Fecha y hora de entrega.
Tiempo estimado de producción.
Tiempo restante.
Prioridad.
Ejemplo:
text

Pedido #0158  
Entrega:  
21 de julio - 17:00  
Tiempo restante:  
2 días 5 horas
Prioridad automática
El sistema calcula automáticamente la urgencia considerando:

Tiempo hasta la entrega.
Cantidad de etapas pendientes.
Cantidad de planchas.
Cantidad de diseños sin confirmar.
Estado del pago.
Resultado:
text

Prioridad:  
🟢 Baja  
🟡 Normal  
🟠 Alta  
🔴 Urgente
Pero siempre debe existir un botón para cambiarla manualmente.

Panel "Necesitan atención hoy"
Al abrir el programa aparecería un panel como este:

text

⚠ Necesitan atención hoy  
Pedido #0158  
Faltan aprobar diseños  
Entrega en 6 horas  
[Continuar]

--------------------  
Pedido #0162  
Listo para imprimir  
[Imprimir]

--------------------  
Pedido #0165  
Esperando imágenes del cliente  
[Ver pedido]
Así no tenés que revisar todos los pedidos uno por uno.

Tiempo estimado de trabajo
Además del tiempo hasta la entrega, el programa puede mostrar una estimación del trabajo restante.
Ejemplo:

text

Pedido  
Tiempo restante hasta la entrega:  
18 horas  
Tiempo estimado para terminar:  
35 minutos  
Estado:  
Sin riesgo
O bien:

text

Entrega en:  
5 horas  
Tiempo estimado:  
1 h 20 min  
Estado:  
⚠ Riesgo de atraso
Esto te ayuda a priorizar antes de que el problema aparezca.

Barra de progreso
Cada pedido tendría dos barras:
Producción

text

Producción  
████████░░░░░

65 %
Tiempo

text

Tiempo disponible  
██████░░░░░░

45 %
Si el tiempo disponible baja más rápido que el avance de producción, el pedido pasa automáticamente a "Alto" o "Urgente".

Estados del pedido
Los estados que habíamos definido eran:

text

Recibido  
↓  
Esperando archivos  
↓  
Diseños confirmados  
↓  
Listo para Armado de Planchas  
↓  
En Armado de Planchas  
↓  
Listo para imprimir  
↓  
Impreso  
↓  
Finalizado  
↓  
Entregado
Y si algo se detiene:

text

Esperando aprobación  
Esperando pago  
Esperando imágenes  
Pendiente  
Bloqueado
Lo que más me gustó
En lugar de mostrar solo "Urgente", el programa podría decirte qué hacer ahora.
Por ejemplo:

text

Siguiente acción recomendada  
Pedido #0158  
✔ Confirmar los diseños del cliente  
Tiempo estimado:  
3 minutos  
Entrega:  
Hoy 17:00  
[Ir al pedido]
O:

text

Siguiente acción recomendada  
Pedido #0164  
✔ Imprimir la plancha  
Tiempo estimado:  
5 minutos  
Entrega:  
Mañana  
[Imprimir]
Eso transforma el programa en un asistente de producción: en lugar de obligarte a decidir constantemente qué sigue, te propone la tarea con mayor impacto según el estado de los pedidos y los tiempos de entrega. Creo que esa función te va a ahorrar mucho tiempo cuando tengas decenas de trabajos abiertos al mismo tiempo.# 🎯 Coordinación Estado ↔ Línea de Tiempo

## Problema Resuelto

Antes había **confusión** entre el "Estado" del pedido y la "Etapa" de la línea de tiempo. Ahora están **perfectamente coordinados**: el estado define directamente la etapa.

---

## ✅ Sistema Coordinado

### Estados Principales (1:1 con Etapas)

Los estados principales **SON** las etapas de la línea de tiempo:

| Estado del Pedido | Etapa de la Línea de Tiempo | Icono |
|-------------------|----------------------------|-------|
| Recibido | Recibido | ● |
| Esperando archivos | Esperando archivos | ● |
| Diseños confirmados | Diseños confirmados | ● |
| Listo para Armado de Planchas | Listo para Armado de Planchas | ● |
| En Armado de Planchas | En Armado de Planchas | ● |
| Listo para imprimir | Listo para imprimir | ● |
| Impreso | Impreso | ● |
| Finalizado | Finalizado | ● |
| Entregado | Entregado | ● |

### Estados Especiales (Bloquean el Flujo)

Estos estados indican que el pedido está **detenido** temporalmente:

| Estado Especial | Se Mapea a Etapa | Uso |
|-----------------|------------------|-----|
| Esperando aprobación | Esperando archivos | Cliente debe aprobar diseños |
| Esperando pago | Recibido | Falta seña o pago completo |
| Pendiente | Recibido | Falta información del cliente |
| Bloqueado | Recibido | Problema que impide avanzar |

**Nota:** Cuando usas un estado especial, deberías completar el campo **"⚠️ Razón si está bloqueado"** para explicar por qué.

### Estados Legacy (Compatibilidad)

Para pedidos antiguos, se mapean automáticamente:

| Estado Antiguo | Se Convierte en |
|----------------|-----------------|
| Nuevo | Recibido |
| En revisión | Esperando archivos |
| En diseño | Esperando archivos |
| Listo para plancha | Listo para Armado de Planchas |
| En producción | En Armado de Planchas |
| Aprobado | Diseños confirmados |
| Presupuesto enviado | Recibido |
| Rechazado | Recibido |

---

## 🎨 Cómo Se Ve en la Interfaz

### En el Formulario de Nuevo Pedido

```
┌────────────────────────────────────────────┐
│          NUEVO PEDIDO                      │
│                                            │
│ Registrá la información del cliente...     │
│ 📍 Etapa en línea de tiempo: Recibido     │
├────────────────────────────────────────────┤
│                                            │
│  Estado: [Recibido ▼]                     │
│           │                                │
│           ↓ Seleccionar                    │
│         • Recibido                         │
│         • Esperando archivos               │
│         • Diseños confirmados              │
│         • Listo para Armado de Planchas    │
│         • En Armado de Planchas            │
│         • Listo para imprimir              │
│         • Impreso                          │
│         • Finalizado                       │
│         • Entregado                        │
│         ─────────────────                  │
│         • Esperando aprobación             │
│         • Esperando pago                   │
│         • Pendiente                        │
│         • Bloqueado                        │
│                                            │
│  💡 El estado define la etapa en la        │
│     línea de tiempo                        │
│                                            │
│  ⚠️ Razón si está bloqueado: [____]       │
│                                            │
└────────────────────────────────────────────┘
```

### En la Lista de Pedidos

La columna **"Etapa"** muestra exactamente el estado del workflow:

```
┌─────┬─────────┬────────────────────────────┬─────────┐
│ 🔴  │ N.º     │ Etapa                      │ Estado  │
├─────┼─────────┼────────────────────────────┼─────────┤
│ 🔴  │ #158    │ Diseños confirmados        │ Normal  │
│ 🟠  │ #162    │ Listo para imprimir        │ Alta    │
│ 🟡  │ #165    │ Esperando archivos         │ Normal  │
│ 🔴  │ #170    │ Recibido                   │ Urgente │
└─────┴─────────┴────────────────────────────┴─────────┘
```

### En el Workspace del Pedido

La línea de tiempo visual refleja el estado:

```
LÍNEA DE TIEMPO
Diseños confirmados · 100% completado

● Recibido
● Esperando archivos
● Diseños confirmados    ← ACTUAL
○ Listo para Armado de Planchas
○ En Armado de Planchas
○ Listo para imprimir
○ Impreso
○ Finalizado
○ Entregado
```

---

## 🔄 Flujo de Trabajo Típico

### Pedido Normal (Sin Problemas)

```
1. Recibido
   ↓ Cliente envía fotos
2. Esperando archivos
   ↓ Diseños listos
3. Diseños confirmados
   ↓ Se prepara para producción
4. Listo para Armado de Planchas
   ↓ Se arma la plancha
5. En Armado de Planchas
   ↓ Plancha terminada
6. Listo para imprimir
   ↓ Se imprime
7. Impreso
   ↓ Control de calidad
8. Finalizado
   ↓ Cliente retira
9. Entregado
```

### Pedido con Bloqueo

```
1. Recibido
   ↓ Cliente no responde
2. [BLOQUEADO: "Cliente no responde WhatsApp"]
   Estado: Pendiente
   Etapa: Recibido
   ↓ Cliente responde y envía fotos
3. Esperando archivos
   ↓ Diseños listos, enviados
4. [BLOQUEADO: "Esperando aprobación del cliente"]
   Estado: Esperando aprobación
   Etapa: Esperando archivos
   ↓ Cliente aprueba
5. Diseños confirmados
   ... continúa normalmente
```

### Pedido sin Seña

```
1. Recibido
   ↓ Cliente no pagó seña
2. [BLOQUEADO: "Falta seña de $500"]
   Estado: Esperando pago
   Etapa: Recibido
   ↓ Se recibe el pago
3. Recibido (se quita el bloqueo)
   ↓ Continúa el flujo normal
4. Esperando archivos
   ...
```

---

## 💻 Implementación Técnica

### Combobox de Estados (Ordenado por Flujo)

```python
ORDER_STATUSES = (
    # Estados principales (en orden del workflow)
    "Recibido",
    "Esperando archivos", 
    "Diseños confirmados",
    "Listo para Armado de Planchas",
    "En Armado de Planchas",
    "Listo para imprimir",
    "Impreso",
    "Finalizado",
    "Entregado",
    # Estados especiales (bloqueantes)
    "Esperando aprobación",
    "Esperando pago",
    "Pendiente",
    "Bloqueado",
)
```

### Mapeo en `app/workflow/timeline.py`

```python
STATE_TO_STAGE = {
    # Estados principales (1:1)
    "Recibido": "Recibido",
    "Esperando archivos": "Esperando archivos",
    "Diseños confirmados": "Diseños confirmados",
    "Listo para Armado de Planchas": "Listo para Armado de Planchas",
    "En Armado de Planchas": "En Armado de Planchas",
    "Listo para imprimir": "Listo para imprimir",
    "Impreso": "Impreso",
    "Finalizado": "Finalizado",
    "Entregado": "Entregado",
    # Estados especiales (bloqueantes)
    "Esperando aprobación": "Esperando archivos",
    "Esperando pago": "Recibido",
    "Pendiente": "Recibido",
    "Bloqueado": "Recibido",
    # Compatibilidad legacy
    "Nuevo": "Recibido",
    "En revisión": "Esperando archivos",
    # ... más mapeos antiguos
}
```

### Sincronización Automática

```python
def sync_status_to_stage(*args):
    selected_status = status.get()
    stage = STATUS_TO_STAGE.get(selected_status, "Recibido")
    current_stage.set(stage)
    
    # Advertencia visual si está bloqueado
    if selected_status in ("Esperando aprobación", "Esperando pago", "Pendiente", "Bloqueado"):
        if hasattr(dialog, 'pending_reason_entry'):
            dialog.pending_reason_entry.configure(highlightcolor="#ff6b35")

status.trace_add("write", sync_status_to_stage)
```

---

## 📊 Ventajas del Sistema Coordinado

### Antes (Confuso)

❌ Estado: "En diseño"
❌ Etapa: "Esperando archivos"
❌ ¿Cuál es correcto?

### Ahora (Claro)

✅ Estado: "Esperando archivos"
✅ Etapa: "Esperando archivos"
✅ Ambos dicen lo mismo

### Beneficios

1. **Eliminación de ambigüedad**: No hay confusión sobre dónde está el pedido
2. **Sincronización automática**: Cambias uno, se actualiza el otro
3. **Menos errores**: No puedes tener estado ≠ etapa
4. **Más claro para el cliente**: Si pregunta, le decís el estado directamente
5. **Filtros coherentes**: Filtrar por "En producción" muestra pedidos en esa etapa
6. **Estados bloqueantes claros**: Sabrás inmediatamente si algo está detenido

---

## 🎯 Casos de Uso

### Crear Pedido Nuevo

1. Abrir "Nuevo pedido"
2. Estado por defecto: **"Recibido"**
3. Etapa mostrada: **"Recibido"** ✓
4. Crear pedido

**Resultado:** Pedido en etapa "Recibido" de la línea de tiempo

### Avanzar el Pedido

1. Abrir pedido existente
2. Cliente envió fotos → Cambiar estado a **"Esperando archivos"**
3. Línea de tiempo se actualiza automáticamente
4. Guardar

**Resultado:** La línea de tiempo muestra "Esperando archivos" como actual

### Bloquear Temporalmente

1. Pedido en "Esperando archivos"
2. Cliente no aprueba → Cambiar a **"Esperando aprobación"**
3. Completar campo "Razón": "Cliente revisando diseños"
4. Guardar

**Resultado:** Pedido bloqueado pero la etapa sigue siendo "Esperando archivos"

### Filtrar Pedidos

1. Ir a lista de pedidos
2. Filtro: **"En producción"**
3. Muestra solo pedidos con estado "En Armado de Planchas"

**Resultado:** Lista filtrada por etapa del workflow

---

## 📝 Notas Importantes

### Para el Usuario

- **Estado = Etapa**: Ahora significan lo mismo
- **Estados especiales**: Úsalos cuando algo bloquea el flujo
- **Razón obligatoria**: Si usas estado bloqueante, explicá por qué
- **Progreso claro**: La línea de tiempo siempre refleja el estado

### Para el Desarrollador

- `ORDER_STATUSES`: Lista de estados en el combobox
- `STATE_TO_STAGE`: Mapeo en `app/workflow/timeline.py`
- `sync_status_to_stage()`: Callback que sincroniza
- `refresh_order_timeline()`: Actualiza la visual en el workspace

---

## 🚀 Migración de Pedidos Antiguos

Los pedidos con estados antiguos se mapean automáticamente:

```python
# Pedido antiguo
status = "Nuevo"  
→ Se mapea a: "Recibido"

# Pedido antiguo
status = "En diseño"
→ Se mapea a: "Esperando archivos"

# Pedido antiguo
status = "Listo para plancha"
→ Se mapea a: "Listo para Armado de Planchas"
```

**No se pierden datos**, solo se normalizan al abrir.

---

**Estado del Sistema:** COORDINADO ✅  
**Fecha:** Julio 2026  
**Resultado:** Estado y Línea de Tiempo trabajan como uno solo
