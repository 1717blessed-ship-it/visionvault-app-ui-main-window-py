# Instalación del Formulario Mejorado de Nuevo Pedido

## Resumen de Mejoras

El nuevo formulario incluye:

✅ **Fecha de pedido** - Se captura la fecha en que se recibe el pedido
✅ **Concepto del pedido** - Campo de texto para describir brevemente qué necesita el cliente
✅ **Descripción detallada** - Área de texto más grande para detalles específicos
✅ **Cliente con nombre y WhatsApp** - Información de contacto organizada
✅ **Fecha y hora de entrega** - Campos separados para mejor precisión
✅ **Scroll con rueda del mouse** - Formulario desplazable para mejor navegación
✅ **Sincronización con línea de tiempo** - El estado se conecta automáticamente con la etapa
✅ **Campos actualizados en la base de datos** - `order_concept` y `order_description`

---

## Características Nuevas

### 🖱️ Scroll con Rueda del Mouse

El formulario ahora soporta scroll vertical con la rueda del mouse, permitiendo navegar fácilmente por todos los campos sin necesidad de usar la barra de desplazamiento.

**Cómo funciona:**
- Mover la rueda hacia arriba/abajo desplaza el contenido
- Se limpia automáticamente el binding cuando se cierra el formulario
- Funciona en todo el área del formulario

### 📍 Sincronización Estado ↔ Línea de Tiempo

Cuando cambias el **Estado** del pedido, la **etapa de la línea de tiempo** se actualiza automáticamente.

**Mapeo Estado → Etapa:**

| Estado | Etapa de la Línea de Tiempo |
|--------|----------------------------|
| Nuevo | Recibido |
| Recibido | Recibido |
| Esperando archivos | Esperando archivos |
| Esperando imágenes | Esperando archivos |
| En revisión | Esperando archivos |
| En diseño | Esperando archivos |
| Diseños confirmados | Diseños confirmados |
| Listo para plancha | Listo para Armado de Planchas |
| En producción | En Armado de Planchas |
| Listo para imprimir | Listo para imprimir |
| Impreso | Impreso |
| Finalizado | Finalizado |
| Entregado | Entregado |

**En el formulario:**
- Debajo del título aparece: **📍 Etapa: [Nombre de la etapa]**
- Se actualiza en tiempo real al cambiar el estado
- Muestra "(se actualiza según el estado elegido)"

**En el workspace del pedido:**
- La línea de tiempo visual se actualiza al guardar
- El panel de línea de tiempo refleja el estado actual
- La barra de progreso se ajusta automáticamente

---

## Paso 1: Base de Datos Actualizada ✓

Los campos ya han sido agregados a la base de datos:
- `order_concept TEXT DEFAULT ''`
- `order_description TEXT DEFAULT ''`

Estos se añadirán automáticamente cuando la aplicación se inicie.

---

## Paso 2: Reemplazar el Método `new_order_dialog`

### Ubicación

Archivo: `app/ui/main_window.py`

### Problema Actual

Hay **4 definiciones duplicadas** del método `new_order_dialog` en las líneas aproximadas:
- Línea 606
- Línea 916
- Línea 983
- Línea 1122

### Solución

**ELIMINAR las primeras 3 definiciones** (líneas 606, 916 y 983) y **REEMPLAZAR la última** (línea 1122) con el código del archivo `new_order_dialog_improved.py`.

### Pasos Detallados

1. **Abrir** `app/ui/main_window.py`

2. **Buscar y eliminar** las siguientes líneas (aproximadamente):

   - **Primera definición** (línea ~606):
     ```python
     def new_order_dialog(self):
         dialog = tk.Toplevel(self)
         ...
     ```
     Eliminar hasta el siguiente método.

   - **Segunda definición** (línea ~916):
     ```python
     def new_order_dialog(self):
         dialog = tk.Toplevel(self)
         ...
     ```
     Eliminar hasta el siguiente método.

   - **Tercera definición** (línea ~983):
     ```python
     def new_order_dialog(self):
         """Formulario de pedido más claro, sin cambiar el flujo ni los datos."""
         ...
     ```
     Eliminar hasta el siguiente método.

3. **Reemplazar la cuarta definición** (línea ~1122) con el contenido completo de `new_order_dialog_improved.py`.

---

## Paso 3: Verificar la Integración

Después de realizar los cambios, verifica que:

1. **No haya duplicados**:
   - Busca `def new_order_dialog` en el archivo
   - Debe aparecer UNA SOLA VEZ

2. **Los imports estén presentes**:
   ```python
   from datetime import datetime
   ```

3. **El método `edit_order_job_dialog` existe**:
   - El nuevo formulario lo usa para editar trabajos
   - Ya existe en tu código actual

---

## Paso 4: Probar el Nuevo Formulario

1. Ejecutar la aplicación
2. Click en "Nuevo pedido"
3. Verificar que aparecen los nuevos campos:
   - 📅 Fecha de pedido (autocompletada con hoy)
   - 📝 Concepto (área de texto)
   - 📄 Descripción (área de texto)
   - 👤 Nombre del cliente
   - 📱 WhatsApp
   - 📆 Fecha de entrega
   - 🕐 Hora de entrega (por defecto 18:00)

---

## Estructura del Nuevo Formulario

```
┌─────────────────────────────────────────────────────────────┐
│                     NUEVO PEDIDO                            │
│                                                             │
│ Registrá la información del cliente, fecha de entrega...   │
│ 📍 Etapa: Recibido (se actualiza según el estado elegido)  │
├─────────────────────────────────────────────────────────────┤
│  ↕️ SCROLL CON RUEDA DEL MOUSE HABILITADO                  │
│  ┌──────────────────────┐   ┌──────────────────────────┐   │
│  │ INFORMACIÓN          │   │ TRABAJOS DEL PEDIDO      │   │
│  │                      │   │                          │   │
│  │ 📅 Fecha de pedido   │   │ Trabajo 1               │   │
│  │ 📝 Concepto          │   │ Material: ...           │   │
│  │ 📄 Descripción       │   │ Tamaño: ...             │   │
│  │                      │   │ Subtotal: ...           │   │
│  │ ────── CLIENTE ───── │   │                          │   │
│  │ 👤 Nombre            │   │ [+ Trabajo] [Editar]    │   │
│  │ 📱 WhatsApp          │   │                          │   │
│  │                      │   │ 1 trabajo(s) · $0       │   │
│  │ ── ENTREGA ────────  │   │                          │   │
│  │ 📆 Fecha  🕐 Hora    │   │                          │   │
│  │ 👨‍💼 Asignado a       │   │                          │   │
│  │ ⚡ Prioridad         │   │                          │   │
│  │ 📌 Estado ←─────────────── CONECTADO A LÍNEA TIEMPO │   │
│  └──────────────────────┘   └──────────────────────────┘   │
│                                                             │
│                          [Cancelar] [Crear pedido]         │
└─────────────────────────────────────────────────────────────┘
```

**Notas de la interfaz:**
- ↕️ El formulario completo es desplazable con la rueda del mouse
- 📍 El indicador de etapa se actualiza en tiempo real
- 📌 El combobox de Estado está conectado a la línea de tiempo

---

## Cómo se Guardan los Datos

### Concepto y Descripción

Se guardan en el campo `observations` con formato:
```
CONCEPTO: [texto del concepto]

DESCRIPCIÓN: [texto de la descripción]
```

### Fecha y Hora de Entrega

Se combinan en `delivery_date` como:
```
2026-07-19 18:00
```

### Fecha de Pedido

Se guarda en `order_date` como:
```
2026-07-18
```

---

## Beneficios del Nuevo Formulario

1. **Organización Visual Mejorada**
   - Panel izquierdo: información del pedido y cliente
   - Panel derecho: trabajos y presupuesto
   - Separadores visuales entre secciones
   - **Scroll fluido con rueda del mouse**

2. **Campos Específicos**
   - Concepto rápido para identificar el pedido
   - Descripción detallada para requisitos específicos
   - Fecha y hora de entrega separadas
   - **Estado conectado a la línea de tiempo**

3. **Mejor Experiencia**
   - Iconos visuales (📅, 👤, 📱, etc.)
   - Campos autocompletados (fecha de hoy, hora 18:00)
   - Validaciones y mensajes claros
   - **Indicador de etapa en tiempo real**
   - **Navegación con rueda del mouse**

4. **Compatibilidad**
   - Mantiene toda la funcionalidad de trabajos múltiples
   - Compatible con el sistema de priorización automática
   - **Sincronización automática con la línea de tiempo**
   - No rompe funcionalidades existentes

---

## Ejemplos de Sincronización

### Flujo Normal de un Pedido

1. **Crear pedido** → Estado: "Nuevo" → Etapa: "Recibido"
2. **Cliente envía fotos** → Estado: "En revisión" → Etapa: "Esperando archivos"
3. **Diseños listos** → Estado: "Diseños confirmados" → Etapa: "Diseños confirmados"
4. **Listo para producción** → Estado: "Listo para plancha" → Etapa: "Listo para Armado de Planchas"
5. **Armando plancha** → Estado: "En producción" → Etapa: "En Armado de Planchas"
6. **Plancha lista** → Estado: "Listo para imprimir" → Etapa: "Listo para imprimir"
7. **Impreso** → Estado: "Impreso" → Etapa: "Impreso"
8. **Completado** → Estado: "Finalizado" → Etapa: "Finalizado"
9. **Cliente retira** → Estado: "Entregado" → Etapa: "Entregado"

### Vista en el Formulario

Cuando cambias el estado en el formulario:

```
Estado: [Esperando archivos ▼]
         ↓
📍 Etapa: Esperando archivos (se actualiza según el estado elegido)
```

### Vista en el Workspace del Pedido

La línea de tiempo visual muestra:

```
● Recibido
● Esperando archivos    ← ACTUAL
○ Diseños confirmados
○ Listo para Armado de Planchas
...
```

---

## Soporte

Si encuentras algún problema:

1. Verifica que solo existe UNA definición de `new_order_dialog`
2. Revisa que todos los imports están presentes
3. Confirma que la base de datos se actualizó (los nuevos campos deben existir)

La aplicación creará automáticamente las columnas `order_concept` y `order_description` la próxima vez que se inicie.

---

**Versión**: 1.0  
**Fecha**: Julio 2026  
**Compatibilidad**: Doccione Studio + Sistema de Línea de Tiempo Inteligente
