# CM HorasExtras

Sistema de gestión de horas extras y francos compensatorios para el personal de CELP (Cooperativa Eléctrica de La Paz), convenio Luz y Fuerza.

---

## Qué hace

- Procesa fichadas del reloj biométrico (archivos Excel) y calcula automáticamente horas extra al 50%, al 100%, comidas y tardanzas por empleado y semana
- Gestiona francos compensatorios: saldo inicial, generados por período, tomados y saldo actual
- Genera PDFs de liquidación por período y por empleado
- Envía reportes semanales de saldos de francos por email a los supervisores de cada departamento
- Expone una interfaz web (Flask) para supervisores y una app de escritorio (Tkinter) para carga y revisión

---

## Arquitectura

```text
main.py                    ← App de escritorio Tkinter (carga de fichadas, PDFs)
servidor.py                ← Backend web Flask (supervisores, francos, cierres)
procesador.py              ← Motor de cálculo de horas extras y francos
pdf_generator.py           ← Generación de PDFs de liquidación
reporte_saldos_francos.py  ← Script de reporte semanal automático (email)
feriados_gui.py            ← UI para gestionar feriados
graficos_ui.py             ← Panel de gráficos estadísticos
resumen_ui.py              ← Pantalla resumen por empleado
horarios_paro.py           ← Configuración de horarios de días de paro
```

### Flujo de datos

```text
Excel de fichadas
      ↓
procesador.py  →  sesion.json  (período activo en memoria)
      ↓
servidor.py    →  datos/cierres.db  (SQLite, períodos cerrados)
      ↓
pdf_generator.py / reporte_saldos_francos.py  →  reportes/
```

---

## Instalación local

**Requisitos:** Python 3.10+, pip

```bash
# Clonar el repositorio
git clone https://github.com/CMLAPAZ/HorasExtrasRelojCoop.git
cd HorasExtrasRelojCoop

# Crear entorno virtual e instalar dependencias
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

**Fuentes:** Copiar los archivos `.ttf` de DejaVu en `recursos/fonts/`:

- `DejaVuSans.ttf`
- `DejaVuSans-Bold.ttf`
- `DejaVuSans-Oblique.ttf`

---

## Cómo correr

### App de escritorio (carga de fichadas)

```bash
.venv\Scripts\python main.py
```

O desde VS Code: configuración **"CM HorasExtras (sin debug, rápido)"** en `.vscode/launch.json`.

### Servidor web local

```bash
.venv\Scripts\python servidor.py
# Abre http://localhost:5000
```

Contraseña de supervisor: definida en variable de entorno `SUPERVISOR_PASS` (default: `cm2026`).

---

## Producción — PythonAnywhere

- **URL:** <https://cmhoras.pythonanywhere.com>
- **Directorio:** `/home/cmhoras/cm_horas/`
- **DB:** `/home/cmhoras/cm_horas/datos/cierres.db`
- **Logs:** `/var/log/cmhoras.pythonanywhere.com.error.log`

### Deploy

```bash
# Desde la consola Bash de PythonAnywhere:
cd /home/cmhoras/cm_horas
git pull origin main
# Luego recargar la web app desde el panel de PythonAnywhere
```

---

## Reporte automático de francos (viernes)

El script `reporte_saldos_francos.py` genera un PDF de saldos de francos por departamento
y lo envía por email a los supervisores configurados.

- **Configuración SMTP:** `config_email.json` (no commiteado, credenciales Gmail)
- **Supervisores:** tabla `supervisores` en la DB, gestionados desde `/configuracion/email`
- **Ejecución:** Tarea Programada de Windows, viernes 08:00, usando `pythonw.exe`

Para correrlo manualmente:

```bash
.venv\Scripts\python reporte_saldos_francos.py
```

---

## Base de datos (SQLite)

| Tabla | Contenido |
|---|---|
| `periodos` | Períodos de liquidación cerrados |
| `periodo_empleados` | Resultados por empleado por período (OT50, OT100, comidas, francos) |
| `francos_tomados` | Francos tomados por empleado (fecha, tipo, días, estado) |
| `francos_saldo_inicial` | Saldo inicial de francos al 04/05/2026 |
| `francos_generados` | Francos generados manualmente (deptos sin fichadas) |
| `francos_semana_manual` | Francos semanales cargados manualmente (Guardias/Internet/Telefonía) |
| `francos_semana_parcial` | Snapshot semanal del período activo |
| `francos_cierre_detalle` | Detalle de francos al cierre de cada período |
| `supervisores` | Supervisores con email y departamentos asignados |
| `empleados_extra` | Empleados de departamentos sin fichadas automáticas |

---

## Departamentos

| Departamento | Fuente de datos |
|---|---|
| Redes | Fichadas del reloj biométrico |
| Guardias | Carga manual semanal |
| Internet | Carga manual semanal |
| Telefonía | Carga manual semanal |
| Administración | Fichadas del reloj biométrico |

---

## Archivos de configuración

| Archivo | Contenido | En git |
|---|---|---|
| `config.json` | Feriados, días de paro, asignaciones especiales, horarios fijos | Sí |
| `config_email.json` | Credenciales SMTP | No |
| `sesion.json` | Período activo en curso | No |
| `recursos/telefonos.json` | Números de WhatsApp por legajo | Sí |

---

## Reglas de negocio clave

- **Jornada normal:** 7 horas. Los primeros 6 minutos de tardanza se toleran.
- **OT50:** horas extra en día hábil (hasta las 21:00)
- **OT100:** horas extra nocturnas (después de las 21:00), fines de semana y feriados
- **Franco compensatorio:** 1 franco cada 7 días de OT acumulados (según convenio)
- **Cuadrilla:** si un grupo del mismo depto entra antes de las 06:00, el sistema infiere el horario grupal automáticamente (04:30 / 05:00 / 05:30)
- **Día de paro:** el cálculo usa el horario de paro configurado para ese depto y mes

---

**No subir al repositorio:** `sesion.json`, `config_email.json`, archivos Excel de fichadas, PDFs generados.
