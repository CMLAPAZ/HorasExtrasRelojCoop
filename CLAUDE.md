# CLAUDE.md — Contexto del proyecto CM HorasExtras

Sistema interno de CELP (Cooperativa Eléctrica de La Paz) para gestión de horas extras
y francos compensatorios del personal. Convenio Luz y Fuerza.

---

## Stack

- **Backend web:** Flask (`servidor.py`, ~2400 líneas) + SQLite (`datos/cierres.db`)
- **Frontend web:** Templates Jinja2 con HTML/CSS inline, sin framework JS
- **App de escritorio:** Tkinter (`main.py`)
- **Motor de cálculo:** `procesador.py` — lee fichadas Excel, produce totales por empleado/semana
- **PDF:** fpdf2 (`pdf_generator.py`), fuentes DejaVu en `recursos/fonts/`
- **Reporte email:** `reporte_saldos_francos.py` — corre cada viernes vía Tarea Programada Windows
- **Venv:** `.venv/Scripts/python.exe` (local Windows)

---

## Archivos principales

| Archivo | Rol |
|---|---|
| `main.py` | App Tkinter: carga fichadas, llama al procesador, genera PDFs, gestiona semanas |
| `servidor.py` | Flask: supervisores, cierres de períodos, francos, email, API JSON |
| `procesador.py` | Lógica pura de cálculo: bloques de trabajo, OT50/OT100, cuadrilla, tardanza |
| `pdf_generator.py` | Genera PDFs de liquidación por empleado y resumen por período |
| `reporte_saldos_francos.py` | Genera PDF de saldos de francos por depto y los envía por email |
| `feriados_gui.py` | Ventana Tkinter para gestionar feriados en config.json |
| `graficos_ui.py` | Panel Tkinter con gráficos estadísticos de horas extras |
| `resumen_ui.py` | Pantalla Tkinter de resumen consolidado |
| `horarios_paro.py` | Helpers para leer/guardar horarios de días de paro |

---

## Producción

- **URL:** https://cmhoras.pythonanywhere.com
- **Directorio:** `/home/cmhoras/cm_horas/`
- **DB:** `/home/cmhoras/cm_horas/datos/cierres.db`
- **Deploy:** `git push` local → `git pull` en consola Bash de PythonAnywhere → recargar web app
- **Logs:** `/var/log/cmhoras.pythonanywhere.com.error.log`

> La DB local (`datos/cierres.db`) y la de PythonAnywhere son independientes.
> Los francos tomados reales están en PythonAnywhere. Nunca correr reportes importantes
> contra la DB local sin verificar que tenga los datos actualizados.

---

## Flujo de datos

```
Excel de fichadas (biométrico)
        ↓
procesador.procesar_fichadas()
        ↓
sesion.json  ← período activo en memoria (no commitear)
        ↓
servidor.py / cierre de período
        ↓
datos/cierres.db  ← períodos cerrados (permanentes)
        ↓
reporte_saldos_francos.py → reportes/reporte_francos_*.pdf → email supervisores
```

---

## Base de datos — tablas clave

| Tabla | Descripción |
|---|---|
| `periodos` | Períodos cerrados (fecha_desde, fecha_hasta, estado ACTIVO/ANULADO) |
| `periodo_empleados` | OT50, OT100, comidas, francos, tardanzas por empleado/período |
| `francos_tomados` | Francos tomados: legajo, tipo (RANGO/SUELTAS), fecha_desde, fecha_hasta, fechas_sueltas, dias, estado, observaciones |
| `francos_saldo_inicial` | Saldo inicial al 04/05/2026 (ajustado 21/05/2026 para Redes y Guardias) |
| `francos_generados` | Francos generados manualmente para deptos sin fichadas |
| `francos_semana_manual` | Francos semanales de Guardias/Internet/Telefonía cargados desde el formulario |
| `francos_semana_parcial` | Snapshot del período activo guardado cada viernes |
| `francos_cierre_detalle` | Copia de francos_tomados al momento del cierre de período |
| `supervisores` | nombre, email, departamentos (JSON), activo |
| `empleados_extra` | Empleados de deptos sin fichadas: Guardias, Internet, Telefonía, Redes (Karen Soto) |

---

## Reglas de negocio

### Cálculo de horas extras (`procesador.py`)

- **Jornada normal:** 7 horas. Tolerancia de tardanza: 6 minutos.
- **Bloque de trabajo:** va desde la ENTRADA hasta la SALIDA. Si cruza medianoche, pertenece íntegramente al día de la entrada.
- **OT50:** horas trabajadas sobre la jornada en día hábil, hasta las 21:00
- **OT100:** horas extra después de las 21:00, fines de semana y feriados
- **Comidas:** se generan si el bloque supera 7h30 (una comida) o 14h (dos comidas)
- **Franco compensatorio:** 1 franco cada 7 días de OT (regla convenio Luz y Fuerza)

### Cuadrilla (inferencia de horario grupal)

Si la mayoría de un departamento entra antes de las 06:00 en un día dado, el sistema
infiere el horario grupal usando el promedio de primeras entradas:
- Antes de 04:45 → 04:30
- 04:45–05:14 → 05:00
- 05:15–05:44 → 05:30
- 05:45+ → 06:00

Los legajos 100 y 101 se excluyen siempre de la inferencia grupal.

### Horario variable de Redes

Redes cambia su horario de inicio según las horas de luz (verano/invierno). El cambio lo
comunica el ingeniero — cuando avisa, hay que actualizar `config.json → horarios_fijos`
con el nuevo horario y rango de fechas.

### Días de paro

Configurados en `config.json → horarios_paro`. Pueden ser globales (string "HH:MM")
o por mes (`{"2026-05": "06:00"}`). En días de paro no se aplica cuadrilla ni horario fijo.

### Asignaciones especiales

En `config.json → asignaciones_especiales`: legajo + rango de fechas + hora de inicio fija.
Tienen prioridad sobre cuadrilla y horario fijo. Se excluyen de la inferencia grupal.

### Saldo de francos

`saldo_actual = saldo_inicial + generados_periodos + generados_manual + generados_sesion - tomados_db`

Tres fuentes de "generados":
1. `periodo_empleados` (cierres automáticos por fichadas)
2. `francos_generados` (carga manual para deptos sin fichadas)
3. `sesion.json` (período activo no cerrado aún)

---

## Departamentos y fuentes

| Depto | Fichadas | Carga manual |
|---|---|---|
| Redes | Sí (biométrico) | No — pero el horario de inicio varía según horas de luz |
| Administración | Sí (biométrico) | No |
| Guardias | No | Semanal desde formulario web |
| Internet | No | Semanal desde formulario web |
| Telefonía | No | Semanal desde formulario web |

Los deptos sin fichadas (Guardias, Internet, Telefonía) tienen sus empleados en
`empleados_extra` y sus francos generados en `francos_semana_manual` y `francos_generados`.

---

## Empleados extra cargados (21/05/2026)

- **GUARDIAS (6):** 113-MAYDANA, 118-GARCILAZO, 124-FORASTIERI, 130-PLIEGO, 131-ESPINOZA, 136-URIONDO
- **INTERNET (4):** 50-GOMEZ NESTOR, 51-SEGUI, 52-FRIZZO, 54-GRUNEVALT
- **TELEFONÍA (3):** 16-BAROLIN FRANCA, 17-LAZARO GOMEZ, 18-CALVET SILVIA PATRICIA
- **REDES (1):** 102-SOTO KAREN
- Cardozo Juan Carlos (INTERNET) NO cargado — todavía no fue contratado

Legajos correctos: CLASSEN DANTE = 129, LOYTI ANDRES = 135.

---

## Configuración de email (`config_email.json`)

```json
{
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "smtp_user": "acmartin2011@gmail.com",
  "smtp_pass": "...",
  "smtp_from_name": "CM Horas Extras"
}
```

No commiteado (está en `.gitignore`). En PythonAnywhere debe existir una copia local.

---

## Rutas web principales (`servidor.py`)

| Ruta | Función |
|---|---|
| `/` | Pantalla principal con tabla de empleados del período activo |
| `/supervisor` | Login y pantalla de supervisores (autenticada) |
| `/francos` | Gestión de francos tomados |
| `/francos/saldos` | Saldos de francos por empleado |
| `/cierres` | Listado de períodos cerrados |
| `/configuracion/email` | Config SMTP y gestión de supervisores |
| `/periodos/<id>/pdf` | Descarga PDF de liquidación del período |

---

## Convenciones

- `_autenticado()` / `_requiere_auth()` — guard de sesión Flask en todas las rutas protegidas
- `_get_db()` — abre conexión SQLite con `row_factory = sqlite3.Row`
- `_empleados_conocidos()` — lista unificada de empleados desde todas las fuentes (DB + sesion.json + empleados_extra)
- Legajos siempre como `str` para comparaciones (pueden tener ceros a la izquierda)
- Departamentos normalizados a minúsculas en procesador.py, a mayúsculas en las vistas web

---

## Features pendientes

### Asignación de horario especial por empleado (Redes)
A veces un empleado de Redes cubre un guardia u otra situación puntual que implica un
horario diferente al del grupo ese día. Hoy eso solo existe para Karen Soto (asignación
permanente en `config.json → asignaciones_especiales`).

**Idea:** extender el formulario web para que el supervisor pueda asignar un horario
especial a cualquier empleado de Redes por un rango de fechas, sin tocar config.json
manualmente. La lógica de `obtener_inicio_asignado()` en `procesador.py` ya soporta esto —
solo faltaría la UI y persistencia.

---

## Notas importantes

- `sesion.json` y `config_email.json` **no se commitean nunca**
- La DB local y la de PythonAnywhere son independientes — siempre verificar contra cuál se opera
- Los backups `backup_*/` son snapshots manuales de sesion.json y semanas, no tocar
- El reporte automático del viernes usa la DB de PythonAnywhere (si corre allí) o la local (si corre en Windows)
