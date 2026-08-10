# CLAUDE.md — CM HorasExtras

Sistema interno de CELP (Cooperativa Eléctrica de La Paz) para gestión de horas extras
y francos compensatorios del personal. Convenio Luz y Fuerza.

---

## Stack

- **Backend web:** Flask (`servidor.py`, ~2400 líneas) + SQLite (`datos/cierres.db`)
- **Frontend web:** Templates Jinja2 con HTML/CSS inline, sin framework JS
- **App de escritorio:** Tkinter (`main.py`) — uso local en Windows
- **Motor de cálculo:** `procesador.py` — lee fichadas Excel, produce totales por empleado/semana
- **PDF:** fpdf2 (`pdf_generator.py`), fuentes DejaVu en `recursos/fonts/`
- **Reporte email:** `reporte_saldos_francos.py` — corre cada viernes vía tarea programada en PythonAnywhere
- **Venv:** `C:\PyEnvs\CM_HorasExtras\Scripts\python.exe` (local Windows, fuera de OneDrive)

---

## Producción

- **URL:** <https://cmhoras.pythonanywhere.com>
- **Directorio:** `/home/cmhoras/cm_horas/`
- **DB:** `/home/cmhoras/cm_horas/datos/cierres.db`
- **Deploy:** `git push` local → `git pull` en consola Bash de PythonAnywhere → recargar web app
- **Logs:** `/var/log/cmhoras.pythonanywhere.com.error.log`

> La DB local (`datos/cierres.db`) y la de PythonAnywhere son **independientes**.
> Los francos tomados reales están en PythonAnywhere. Nunca correr reportes contra la DB
> local sin verificar que tenga los datos actualizados.

---

## ⚠️ REGLA CRÍTICA: Nunca mezclar departamentos

Cada empleado pertenece a **un único departamento**. Tokens, confirmaciones, períodos,
francos y reportes son siempre **por departamento separado**. Cualquier consulta, cierre
o reporte que combine datos de dos departamentos distintos es un error de diseño.

- Los filtros por depto deben ser explícitos en TODAS las consultas
- `_empleados_conocidos()` devuelve todos los empleados; siempre filtrar por depto antes de operar
- El reporte de saldos genera **1 PDF por departamento**
- El cierre de período se hace depto por depto (o "todos" si se selecciona expresamente)

---

## Archivos principales

| Archivo | Rol |
|---|---|
| `servidor.py` | Flask: auth, carga de fichadas, confirmaciones, cierres, francos, email, API JSON |
| `procesador.py` | Lógica pura de cálculo: bloques de trabajo, OT50/OT100, cuadrilla, tardanza |
| `departamentos.py` | Normalización centralizada de nombres de departamento (sin deps Flask); usado por servidor.py y reporte_saldos_francos.py |
| `pdf_generator.py` | Genera PDFs de liquidación por empleado y resumen consolidado |
| `reporte_saldos_francos.py` | Genera PDF de saldos de francos por depto y los envía por email |
| `main.py` | App Tkinter: carga fichadas, llama al procesador, genera PDFs, gestiona semanas |
| `feriados_gui.py` | Ventana Tkinter para gestionar feriados en config.json |
| `graficos_ui.py` | Panel Tkinter con gráficos estadísticos de horas extras |
| `resumen_ui.py` | Pantalla Tkinter de resumen consolidado |
| `horarios_paro.py` | Helpers para leer/guardar horarios de días de paro |
| `puntualidad_db.py` | Persistencia SQLite para módulo de puntualidad (solo escritorio) |
| `puntualidad_service.py` | Motor de cálculo de puntualidad: importa procesador.py en modo lectura |
| `puntualidad_ui.py` | UI Tkinter independiente de puntualidad (NO integrada a main.py aún) |

---

## Flujo de datos

```text
Excel de fichadas (biométrico)
        ↓
procesador.procesar_fichadas()
        ↓
sesion.json  ← período activo en memoria (no commitear)
        ↓
servidor.py / cierre de período  →  confirmaciones/periodo_XXX/  (JSONs + PDF)
        ↓                        →  reportes/francos_periodo_XXX.pdf (PDF francos)
datos/cierres.db  ← períodos cerrados (permanentes)
        ↓
reporte_saldos_francos.py → reportes/reporte_francos_{DEPTO}_{FECHA}.pdf → email supervisores
```

---

## Directorios del proyecto

| Directorio | Contenido |
|---|---|
| `semanas/` | CSVs de fichadas procesadas (`semana_N.csv`) + `metadata.json` |
| `confirmaciones/` | JSONs de confirmaciones del período activo + subdirs `periodo_XXX/` (archivadas al cerrar) |
| `periodos/` | JSONs de respaldo de cierres completos |
| `reportes/` | PDFs generados: francos de cierre, saldos semanales |
| `recursos/` | `telefonos.json`, `excluidos_ot.json`, `config.json`, `fonts/` (DejaVu) |
| `datos/` | `cierres.db` (SQLite) |
| `templates/` | Templates Jinja2 HTML |

---

## Base de datos — tablas

| Tabla | Descripción |
|---|---|
| `periodos` | Períodos cerrados: fecha_desde, fecha_hasta, semanas, departamento, estado (ACTIVO/ANULADO) |
| `periodo_empleados` | OT50, OT100, comidas, francos, tardanzas por empleado/período |
| `francos_tomados` | Francos tomados: legajo, tipo (UNICO/RANGO/SUELTAS), fecha_desde, fecha_hasta, fechas_sueltas, dias, estado, observaciones, **cierre_francos_id**, **estado_antes_cierre** |
| `francos_saldo_inicial` | Saldo inicial por legajo; columnas `+tomados_al_corte`, `+gen_extra_al_corte`, `+fecha_corte` (agregadas 03/06/2026) |
| `francos_generados` | Francos generados manualmente para deptos sin fichadas; **+cierre_francos_id** |
| `francos_semana_manual` | Francos semanales de Guardias/Internet/Telefonía/Ingenieros cargados desde el formulario web; **+cierre_francos_id** |
| `francos_semana_parcial` | Snapshot del período activo guardado cada viernes (borrado al cerrar el período) |
| `francos_cierre_detalle` | Copia de francos_tomados al momento de cada cierre (historial inmutable) |
| `cierres_francos` | Cierres manuales (deptos sin fichadas: Guardias/Internet/Telefonía/Ingenieros — la ruta `/francos/cierre/nuevo` rechaza explícitamente Redes/Administración desde el 05/08/2026, y el selector `cf-depto` de `periodos_historial.html` ya no los lista): **+base_anterior** (JSON snapshot reversible), **+fecha_anulacion**, **+motivo_anulacion**, **+usuario_anulacion** |
| `supervisores` | nombre, email, departamentos (JSON array), activo |
| `empleados_extra` | Empleados de deptos sin fichadas: Guardias, Internet, Telefonía, **Ingenieros** + Karen Soto (Redes) |

**Movimientos bloqueados**: cuando `cierre_francos_id IS NOT NULL` en `francos_tomados`, `francos_generados` o `francos_semana_manual`, el movimiento está cerrado y no se puede eliminar, modificar ni aprobar. Solo se desbloquea anulando el cierre.

---

## Cierre mensual — qué genera

Al ejecutar `/periodo/cerrar` (POST) el sistema produce:

### En base de datos

1. Registro en `periodos` (id del cierre, fechas, semanas, depto, timestamp)
2. Un registro en `periodo_empleados` por cada empleado del cierre (OT50, OT100, comidas, francos, tardanzas, confirmado)
3. Copia de `francos_tomados` vigentes al momento en `francos_cierre_detalle` (vía `_snapshot_francos_cierre`)
4. Borrado de `francos_semana_parcial` de las semanas incluidas en el cierre

### En disco

5. **PDF de francos tomados** del cierre: `reportes/francos_periodo_{ID}.pdf`
   - Formato apaisado (landscape)
   - Columnas: Legajo, Nombre, Tipo, Fechas, Días, Estado, Emitido, Autorizado, Observaciones
   - Un registro por franco tomado activo en el período
6. **Directorio de confirmaciones archivadas**: `confirmaciones/periodo_{ID}/`
   - Un JSON por empleado (las confirmaciones que tenía al cerrar)
7. Borrado de tokens activos de las semanas cerradas en `sesion.json`

### PDF de confirmaciones (bajo demanda)

Al descargar `/periodos/confirmaciones_pdf/<id>` se genera:

- **PDF de confirmaciones del cierre**: descripción por empleado + pendientes
- Generado por `_generar_pdf_confirmaciones_cierre()`

### Reporte semanal automático (cada viernes, PythonAnywhere)

`reporte_saldos_francos.py` genera independientemente del cierre:

- **1 PDF por departamento**: `reportes/reporte_francos_{DEPTO}_{FECHA}.pdf`
- Tabla: Legajo, Nombre, Saldo Inicial, Generados (períodos + manual + parciales), Tomados, **Saldo Actual**
- Sub-filas de detalle de francos tomados (fechas, estado, observaciones)
- Colores: saldo positivo → verde, negativo → rojo, cero → gris
- Enviado por email a los supervisores asignados a cada departamento

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

Si la mayoría del depto entra antes de las 06:00 en un día dado, el sistema infiere
el horario grupal por el promedio de primeras entradas:

- Antes de 04:45 → 04:30 | 04:45–05:14 → 05:00 | 05:15–05:44 → 05:30 | 05:45+ → 06:00

Los legajos 100 y 101 se excluyen siempre de la inferencia grupal.

### Resolución de hora de inicio (orden de prioridad)

1. `asignaciones_especiales` en `config.json` (más alta prioridad)
2. `horarios_paro` en `config.json` (en día de paro, no aplica cuadrilla ni horario fijo)
3. `horarios_fijos` en `config.json` (fijo por depto + rango de fechas)
4. Cuadrilla inferida (promedio grupal)
5. 06:00 por defecto

### Saldo de francos

```text
saldo_actual = saldo_inicial + generados_periodos + generados_manual + generados_sesion - tomados_db
```

Fuentes de "generados":

1. `periodo_empleados` — cierres automáticos por fichadas
2. `francos_generados` — carga manual para deptos sin fichadas
3. `sesion.json` — período activo no cerrado aún

### Validación de francos tomados

- No pueden solaparse con otros francos del mismo empleado
- Solo fechas hábiles (lun–vie), excepto GUARDIAS que pueden tomar cualquier día
- Tipos: UNICO (un solo día), RANGO (desde-hasta), SUELTAS (lista de fechas)

---

## Departamentos y fuentes

| Depto | Fichadas procesadas por el sistema | Carga manual | Horario variable |
|---|---|---|---|
| Redes | Sí (biométrico) | No | Sí — varía verano/invierno |
| Administración | Sí (biométrico) | No | No |
| Guardias | No | Semanal desde formulario web | No |
| Internet | No | Semanal desde formulario web | No |
| Telefonía | No | Semanal desde formulario web | No |
| **Ingenieros** | No | Cierre manual mensual | No |

**Guardias, Internet, Telefonía e Ingenieros fichan igual que el resto** (tienen reloj
biométrico) — el sistema simplemente **no procesa esas fichadas** para estos 4
departamentos, porque su horario es demasiado complejo/variable para calcularlo
automáticamente con `procesador.py`. Sus francos se llevan aparte, con empleados en
`empleados_extra` y francos generados en `francos_semana_manual` + `francos_generados`.
No confundir "sin fichadas procesadas por el sistema" con "sin reloj biométrico".

**Legajos 100 y 101** (MANCIONI y GATTI) están **excluidos de todo procesamiento biométrico**: `procesador.py` los filtra en `_df_to_registros()` y `LEGAJOS_EXCLUIR_PROCESAMIENTO = {"100", "101"}`. Sus francos se gestionan exclusivamente como Ingenieros desde el módulo manual. `_empleados_conocidos()` da prioridad a `empleados_extra` para esos legajos, ignorando cualquier sesión biométrica que los traiga como Redes.

---

## Empleados extra cargados

- **INGENIEROS (2):** 100-MANCIONI MARTIN, 101-GATTI MARCELO *(incorporados julio 2026; excluidos del biométrico)*
- **GUARDIAS (6):** 113-MAYDANA, 118-GARCILAZO, 124-FORASTIERI, 130-PLIEGO, 131-ESPINOZA, 136-URIONDO
- **INTERNET (4):** 50-GOMEZ NESTOR, 51-SEGUI, 52-FRIZZO, 54-GRUNEVALT
- **TELEFONÍA (3):** 16-BAROLIN FRANCA, 17-LAZARO GOMEZ, 18-CALVET SILVIA PATRICIA
- **REDES (1):** 102-SOTO KAREN
- Cardozo Juan Carlos (INTERNET) NO cargado — todavía no fue contratado

Legajos correctos: CLASSEN DANTE = 129, LOYTI ANDRES = 135.

---

## Variables de entorno (con defaults)

| Variable | Default | Descripción |
|---|---|---|
| `SECRET_KEY` | `cm_horas_secret_2026` | Clave de sesión Flask |
| `SUPERVISOR_PASS` | `cm2026` | Contraseña de acceso supervisor |
| `FIRMA_SUPERVISOR` | `CM - Carola Martin` | Nombre en reportes y PDFs |
| `WA_BASE_URL` | `""` | Base URL para links WhatsApp (vacío = usa host del request) |

---

## Rutas Flask completas (`servidor.py`)

### Públicas (sin auth)

| Método | Ruta | Función | Descripción |
|---|---|---|---|
| GET | `/e/<token>` | `empleado()` | Página de confirmación de horas para el empleado |
| POST | `/e/<token>/confirmar` | `confirmar()` | Recibe descripción + confirma; guarda JSON en `confirmaciones/` |
| GET/POST | `/login` | `login()` | Login de supervisores |
| GET | `/logout` | `logout()` | Cierra sesión |

### Supervisor (requieren auth)

| Método | Ruta | Función | Descripción |
|---|---|---|---|
| GET | `/supervisor` | `index()` | Panel principal: carga fichadas, estado de confirmaciones, semanas |
| POST | `/telefonos/upload` | `telefonos_upload()` | Actualiza `recursos/telefonos.json` desde Excel |
| POST | `/detectar-departamentos` | `detectar_departamentos()` | Devuelve departamentos únicos del CSV de fichadas |
| POST | `/procesar` | `procesar()` | Procesa CSV; genera tokens; crea links de confirmación |
| POST | `/semanas/<n>/reprocesar` | `reprocesar_semana(n)` | Actualiza datos de una semana existente |
| GET | `/semanas` | `semanas()` | Lista semanas con resumen (JSON) |
| GET | `/semanas/<n>/links` | `semana_links(n)` | Lista links + URLs de WhatsApp por empleado |
| POST | `/semanas/<n>/eliminar` | `eliminar_semana(n)` | Elimina semana; borra tokens y francos parciales |
| POST | `/semanas/<n>/guardar-francos` | `guardar_francos_semana(n)` | Guarda saldo parcial de francos de una semana en DB |
| POST | `/semanas/guardar-francos-todos` | `guardar_francos_todos()` | Guarda francos de todas las semanas activas |
| POST | `/semanas/<n>/regenerar` | `regenerar_semana(n)` | Regenera links para empleados pendientes |
| GET | `/semanas/<n>/pdf` | `semana_pdf(n)` | **PDF detallado día a día** de la semana N (para el supervisor el viernes) |
| GET | `/semanas/acumulado/pdf` | `semanas_acumulado_pdf()` | **PDF acumulado** de varias semanas; params: `desde`, `hasta`, `depto` |
| GET | `/periodos/<pid>/informe_completo` | `periodos_informe_completo(pid)` | **PDF completo del cierre**: horas + resumen + saldo francos + detalle tomados |
| GET | `/estado` | `estado()` | Estado de confirmaciones por empleado (JSON) |
| GET | `/historial` | `historial()` | Historial de confirmaciones, filtrable por depto y semana |
| GET | `/historial/acumulado` | `historial_acumulado()` | Acumulado de OT por empleado y semana |
| GET | `/periodo` | `periodo()` | Gestión de períodos: selector semanas + depto |
| GET | `/periodo/resumen` | `periodo_resumen()` | Resumen acumulado del período (JSON) |
| GET | `/periodo/exportar` | `periodo_exportar()` | Exporta período como CSV descargable |
| GET | `/periodo/confirmaciones_pdf` | `periodo_confirmaciones_pdf()` | PDF de confirmaciones del período parcial activo |
| POST | `/periodo/cerrar` | `periodo_cerrar()` | **Cierra período**: guarda en DB, archiva confirmaciones, genera PDFs |
| GET | `/periodos/historial` | `periodos_historial()` | Listado de todos los cierres desde DB |
| GET | `/periodos/ver/<pid>` | `periodos_ver(pid)` | Vista detallada de un cierre |
| GET | `/periodos/francos_pdf/<pid>` | `periodos_francos_pdf(pid)` | Ver (inline) PDF de francos tomados snapshoteados al cierre (`francos_cierre_detalle`); muestra fecha real del cierre, "Reimpreso el" para la fecha actual |
| GET | `/periodos/confirmaciones_pdf/<pid>` | `periodos_confirmaciones_pdf(pid)` | Descarga PDF de confirmaciones archivadas del cierre |
| POST | `/periodos/anular/<pid>` | `periodo_anular(pid)` | Anula un cierre (estado ANULADO); requiere motivo |
| GET | `/francos` | `francos()` | Gestión de francos tomados: tabla de saldos + registrar nuevo |
| POST | `/francos/nuevo` | `francos_nuevo()` | Registra nuevo franco tomado; valida solapamiento |
| POST | `/francos/modificar/<fid>` | `francos_modificar(fid)` | Modifica franco existente |
| POST | `/francos/eliminar/<fid>` | `francos_eliminar(fid)` | Elimina franco tomado |
| GET | `/francos/saldos` | `francos_saldos()` | Saldos actuales de francos por empleado (JSON) |
| POST | `/francos/cierre/anular/<cid>` | `francos_cierre_anular(cid)` | Anula el **último** cierre activo del depto; restaura `francos_saldo_inicial` desde `base_anterior`; desbloquea movimientos vinculados |
| POST | `/francos/planilla/actualizar` | `francos_planilla_actualizar()` | Recibe planilla Excel + mes; escribe Franco Orig. (col G) y Franco Tom. (col H) desde los cierres activos de Ingenieros y Guardias |
| GET | `/empleados/importar` | `empleados_importar()` | Importación de empleados sin fichadas |
| GET | `/configuracion/email` | `configuracion_email()` | Configuración SMTP y supervisores |

### Admin (protegidas, uso excepcional)

| Método | Ruta | Función | Descripción |
|---|---|---|---|
| POST | `/admin/restaurar-confirmaciones` | `admin_restaurar_confirmaciones()` | Restaura confirmaciones desde JSONs a sesión activa |
| POST | `/admin/recortar-semana` | `admin_recortar_semana()` | Recorta semana al rango lunes-domingo exacto |
| POST | `/admin/reset` | `admin_reset()` | **⚠️ DESTRUCTIVA**: borra todo (sesión, confirmaciones, semanas, DB) |

---

## Templates HTML

| Template | Título | Qué muestra |
|---|---|---|
| `supervisor.html` | CM Horas Extras — Supervisor | Panel principal: carga CSV, semanas, estado confirmaciones, teléfonos |
| `empleado.html` | Mis horas — {nombre} | Confirmación del empleado: resumen OT + detalle días + textarea descripción |
| `login.html` | CM Horas Extras — Ingresar | Formulario de contraseña con toggle mostrar/ocultar |
| `francos.html` | CM Horas Extras — Francos Tomados | Registrar franco (tipo UNICO/RANGO/SUELTAS) + tabla de saldos por depto |
| `francos_saldos.html` | Saldos de francos | Tabla imprimible de saldos por depto |
| `periodo.html` | CM Horas Extras — Períodos | Selector semanas + depto; resumen tabular + acciones (PDF, CSV, cerrar) |
| `historial.html` | CM Horas Extras - Confirmaciones | Historial filtrable por depto y semana |
| `historial_acumulado.html` | CM Horas Extras - Acumulado | OT acumulado por empleado y semana |
| `periodos_historial.html` | Cierres realizados | Listado histórico de cierres (ACTIVO/ANULADO) |
| `periodo_detalle.html` | Detalle del cierre #{id} | Empleados, totales, francos archivados + botón PDF |
| `empleados_importar.html` | Importar empleados extra | Carga CSV de empleados sin biométrico |
| `configuracion_email.html` | Configuración de Email | SMTP + gestión de supervisores por depto |
| `confirmado.html` | Confirmación recibida | Pantalla de éxito tras confirmar |
| `confirmaciones_cierre.html` | Confirmaciones del cierre | Fallback HTML si falla generación de PDF |
| `error.html` | Error | Página de error genérica |

---

## Funciones auxiliares `servidor.py`

### Persistencia y DB

| Función | Qué hace |
|---|---|
| `_get_db()` | Abre conexión SQLite; configura `row_factory = sqlite3.Row` |
| `_init_db()` | Crea tablas + aplica migraciones via ALTER TABLE (idempotente) |
| `_cargar_sesion()` | Lee `sesion.json`; retorna `{}` si no existe o está corrupto |
| `_guardar_sesion(s)` | Persiste período activo en `sesion.json` |
| `_cargar_metadata()` | Lee `semanas/metadata.json` (contador global + lista de semanas) |
| `_guardar_metadata(m)` | Persiste `metadata.json` |
| `_guardar_semana_csv(n, df)` | Guarda DataFrame de fichadas como `semanas/semana_N.csv` |
| `_cargar_semana_csv(n)` | Lee `semanas/semana_N.csv` como DataFrame |
| `_cargar_telefonos()` | Lee `recursos/telefonos.json` (legajo → teléfono) |
| `_guardar_telefonos(t)` | Persiste telefonos |
| `_cargar_excluidos_ot()` | Lee `recursos/excluidos_ot.json` (legajos que no generan OT) |

### Auth

| Función | Qué hace |
|---|---|
| `_autenticado()` | Verifica si `session["auth"] is True` |
| `_requiere_auth()` | Redirige a `/login` con `next=` si no autenticado |

### Confirmaciones

| Función | Qué hace |
|---|---|
| `_archivos_confirmacion()` | Lista JSONs en `confirmaciones/` (desc por fecha) |
| `_clave_confirmacion(data)` | Clave única (depto, legajo, semana) para deduplicar |
| `_fechas_confirmacion(data)` | Extrae lista de dates desde `data["dias"]` |
| `_resolver_semana_confirmacion(data, meta)` | Resuelve número de semana global y por depto |
| `_score_confirmacion(data)` | Puntaje para elegir la mejor confirmación en duplicados |
| `_semana_meta_por_numero(meta, semana, dept)` | Busca metadata de semana por número+depto |
| `_ajustar_confirmacion_a_semana(data, meta, sem, depto)` | Filtra días al rango lun-dom de la semana |
| `_leer_historial(semana, depto)` | Lee confirmaciones activas desde archivos + sesión; scoring para deduplicar |
| `_restaurar_confirmaciones_desde_archivos(depto)` | Fallback: restaura confirmaciones de JSONs a sesión activa |
| `_recalcular_totales_token(d)` | Recalcula OT/comidas/francos/tardanzas desde días del token |
| `_pendientes_cierre(confirmaciones, empleados)` | Empleados que no confirmaron pero están en el cierre |

### Procesamiento de fichadas

| Función | Qué hace |
|---|---|
| `_leer_archivo(fs)` | Lee archivo subido (Excel o CSV); detecta encoding y separador |
| `_normalizar_columnas(df)` | Renombra columnas con aliases del reloj biométrico |
| `_procesar_empleados(df, deptos)` | Procesa DataFrame; retorna (empleados, fecha_desde, fecha_hasta) |
| `_rango_lunes_domingo(fechas)` | Calcula rango lun-dom que contiene todas las fechas |
| `_filtrar_empleados_por_rango(empleados, fd, fh)` | Filtra al rango de fechas |
| `_preparar_dias(registros)` | Convierte registros planos a estructura de días con tramos |
| `_crear_tokens(empleados, sem_n, sem_depto, base_url)` | Genera tokens únicos + links de confirmación |
| `_recortar_semana_lunes_domingo(n, depto)` | Recorta días de semana al rango lun-dom exacto |

### Cálculo de francos y saldos

| Función | Qué hace |
|---|---|
| `_calcular_periodo(desde, hasta, depto)` | Acumula horas del período desde historial + sesión pendiente |
| `_calcular_saldos()` | Saldo de francos: inicial + generados - tomados (todas las fuentes) |
| `_empleados_conocidos()` | Lista deduplicada desde `empleados_extra` + `periodo_empleados` + sesión; legajos 100/101 siempre vienen de empleados_extra (Ingenieros) |
| `_departamentos_francos_disponibles(empleados, incluir_ocultos)` | Lista canónica de deptos para todos los selectores del módulo Francos; garantiza que Ingenieros aparezca aunque no tenga movimientos aún |
| `_aplicar_exclusiones_ot(empleados)` | Marca empleados como `excluido_ot` |
| `_es_guardias(conn, legajo)` | Verifica si el empleado pertenece a GUARDIAS |
| `_validar_franco_nuevo(conn, leg, tipo, fd, fh, fechas_sueltas, exclude_id)` | Valida fechas hábiles y no-solapamiento |
| `_fechas_del_registro(tipo, fd, fh, fechas_sueltas, feriados)` | Resuelve fechas efectivas según tipo de franco |
| `_dias_habiles(fd, fh)` | Cuenta días hábiles entre fechas excluyendo feriados |
| `_fechas_habiles_set(desde, hasta, feriados)` | Retorna conjunto de dates hábiles |
| `_cargar_feriados_config()` | Lee feriados desde `config.json` |
| `_vincular_movimientos_cierre_francos(conn, cierre_id, legajos, fecha_hasta)` | Setea `cierre_francos_id` en tomados/generados/semanales; marca tomados como 'Cerrado' guardando estado anterior en `estado_antes_cierre` |
| `_snapshot_base_saldo_manual(conn, legajos)` | Foto de `francos_saldo_inicial` antes del cierre manual (guardada en `cierres_francos.base_anterior` para reversión) |
| `_cierres_francos_del_mes(conn, mes)` | Último cierre activo del mes para Ingenieros y Guardias (para exportar a planilla Excel) |
| `_actualizar_planilla_francos(contenido, mes, cierres)` | Escribe columnas G (Franco Orig.) y H (Franco Tom.) en la hoja mensual de la planilla Excel |

### PDFs

| Función | Qué hace |
|---|---|
| `_snapshot_francos_cierre(conn, pid, fd, fh)` | Copia `francos_tomados` a `francos_cierre_detalle` + genera PDF |
| `_generar_pdf_francos_cierre(pid, francos, fd, fh)` | PDF apaisado de francos tomados del cierre |
| `_generar_pdf_confirmaciones_cierre(periodo, empleados)` | PDF de confirmaciones + pendientes del cierre |
| `_generar_pdf_confirmaciones_parcial(todos, info)` | PDF de confirmaciones del período parcial activo |
| `_leer_confirmaciones_cierre(periodo)` | Lee JSONs archivados de un cierre desde `confirmaciones/periodo_XXX/` |
| `_mapa_semanas_visibles_periodo(periodo)` | Mapa semana_global → número_visible para el cierre |
| `_aplicar_semanas_visibles(empleados, periodo)` | Mapea semanas visibles en empleados del cierre |
| `_pdf_bytes(pdf)` | Convierte FPDF a bytes (maneja latin-1) |
| `_pdf_cell_text(value)` | Convierte value a string seguro para celdas PDF |

### Utilidades

| Función | Qué hace |
|---|---|
| `_dia_semana(fecha_str)` | Retorna nombre del día de la semana en español |
| `_parse_fecha(s)` | Parsea string a date ('%Y-%m-%d' o '%d/%m/%Y') |
| `_parse_td(s)` | Parsea timedelta desde "HH:MM:SS" |
| `_parse_hm(s)` | Parsea timedelta desde "XhYm" |
| `_fmt_hm(td)` | Formatea timedelta a "XhYZm" |
| `_legajo_key(x)` | Clave de ordenamiento: legajo a int |
| `_normalizar_departamento_web(nombre)` | Normaliza depto (lowercase, sin acentos, aliases: "redes", "administracion") |
| `_nombre_departamento_visible(nombre)` | Retorna nombre visible ("administracion" → "Administración") |
| `_normalizar_valor_excel(v)` | Normaliza valores Excel (elimina ".0", vacíos a "") |
| `_wa_url(legajo, nombre, url, totales, dias)` | Genera URL de WhatsApp con mensaje de horas extras |

---

## Funciones `procesador.py`

| Función / Constante | Qué hace |
|---|---|
| `LEGAJOS_EXCLUIR_PROCESAMIENTO` | `{"100", "101"}` — Mancioni y Gatti excluidos de TODO procesamiento biométrico |
| `EXCLUIR_DE_INFERENCIA` | Alias de `LEGAJOS_EXCLUIR_PROCESAMIENTO` (usado en cuadrilla) |
| `cargar_config()` | Lee `config.json` completo |
| `cargar_feriados(config)` | Extrae set de dates de feriados |
| `cargar_dias_paro(config)` | Extrae set de fechas de paro |
| `normalizar_depto(d)` | Convierte a lowercase normalizado |
| `is_weekend(d)` | True si sábado o domingo |
| `obtener_horario_fijo(depto, d, config)` | Busca horario fijo para depto+fecha |
| `obtener_horario_paro(depto, d, config)` | Busca horario de paro (global o por mes) |
| `resolver_hora_inicio(d, depto, inicio_grupal, config, es_paro, legajo)` | Resuelve hora de inicio aplicando prioridades |
| `cargar_asignaciones_especiales(path)` | Lee asignaciones especiales de `config.json` |
| `obtener_inicio_asignado(asignaciones, legajo, d)` | Busca asignación especial vigente para legajo+fecha |
| `inferir_inicio_grupal(registros, asignaciones, feriados, dias_paro, excluir_legajos)` | **Núcleo de cuadrilla**: infiere hora de entrada grupal; devuelve `{(depto, fecha, legajo): hora}` |
| `_df_to_registros(df)` | Convierte DataFrame a tuplas; **filtra legajos 100/101 antes de convertir** |
| `_agrupar_por_empleado(registros)` | Agrupa por (depto, legajo, nombre); ordena cronológicamente |
| `_limpiar_y_emparejar(eventos)` | Arma pares entrada-salida; cierra tramos incompletos |
| `_debe_imputarse_al_dia_anterior(e, s, ...)` | Detecta si tramo de madrugada pertenece al día anterior |
| `_calcular_por_dia(pares, feriados, depto, inicio_grupal, legajo, ...)` | **Motor principal**: OT50/OT100/comidas/franco/tardanza por día |
| `procesar_fichadas(df, feriados, inicio_variable, excluir_tardanza)` | **API pública**: procesa DataFrame; retorna estructura por empleado |
| `aplanar_registros_por_tramo(resultados)` | Convierte estructura jerárquica a lista plana (una fila por tramo) |
| `aplanar_a_dataframe(resultados)` | Retorna DataFrame listo para exportar a Excel |

---

## Funciones `pdf_generator.py`

| Función / Método | Qué produce |
|---|---|
| `_td_from_any(x)` | Convierte timedelta/string/número a timedelta; fallback = 0 |
| `formato_horas(td)` | Formatea timedelta a "HH:MM:SS" |
| `_round_to_hour(td)` | Redondea al número de horas enteras (umbral 30 min) |
| `_parse_fecha(s)` | Parsea fecha de string a date |
| `_resource_path(*relative)` | Ruta a recursos (maneja PyInstaller congelado) |
| `PDFGeneral.header()` | Encabezado con título del PDF |
| `PDFGeneral.footer()` | Pie con número de página |
| `PDFGeneral.portada_abreviaciones(mes)` | Primera página: leyenda de símbolos (★ FER, ◆ SAB, ✦ FRANCO, etc.) |
| `PDFGeneral.encabezado_empleado(legajo, nombre, depto)` | Encabezado por empleado |
| `PDFGeneral.tabla_registros(registros, excluido_ot)` | Tabla por empleado: Fecha, Entrada, Salida, Normales, 50%, 100%, Comida, Franco, Tarde; colores feriado/finde |
| `generar_pdf_general(data, mes, salida, feriados, grosor_lunes)` | PDF completo: portada + un empleado por página |
| `generar_pdf_resumen(data, mes, salida, feriados, grosor_lunes)` | PDF resumen: una fila por empleado con totales |

---

## Convenciones de código

- `_autenticado()` / `_requiere_auth()` — guard de sesión en todas las rutas protegidas
- `_get_db()` — conexión SQLite con `row_factory = sqlite3.Row`
- `_empleados_conocidos()` — lista unificada; **siempre filtrar por depto antes de operar**
- `_departamentos_francos_disponibles()` — usar en todos los selectores de Francos; garantiza que Ingenieros esté presente
- Legajos siempre como `str` para comparaciones (pueden tener ceros a la izquierda)
- Departamentos: minúsculas en `procesador.py`, mayúsculas en vistas web
- `_normalizar_departamento_web()` antes de cualquier comparación por depto en el servidor
- `departamentos.py` — normalización canónica independiente de Flask; usar `clave_canonica()` / `nombre_visible()` / `mismo_departamento()` en lugar de strings ad-hoc
- Movimientos vinculados (`cierre_francos_id IS NOT NULL`) son de solo lectura — verificar antes de cualquier UPDATE/DELETE sobre francos_tomados, francos_generados, francos_semana_manual

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

No commiteado (está en `.gitignore`). En PythonAnywhere debe existir copia local.

---

## Refactoring pendiente — División de `servidor.py`

**Cuándo:** después del cierre de mayo 2026, cuando todas las features estén estables.

**Orden sugerido (menor a mayor riesgo):**

1. `rutas_email.py` — config SMTP, supervisores, reporte semanal
2. `rutas_francos.py` — francos tomados, saldos, carga manual
3. `rutas_cierres.py` — períodos, cierre, anulación, PDFs
4. `servidor.py` — queda solo con auth, sesión, carga de fichadas y rutas principales

**Reglas:** un módulo a la vez sin cambiar lógica, verificar en PythonAnywhere, un commit por módulo.

---

## Implementado en sesión 03/06/2026

### Informes semanales imprimibles (supervisor.html)

Botones nuevos en cada fila de semana del panel supervisor:

- **🖨 Informe semana** → `GET /semanas/<n>/pdf` — PDF día a día de esa semana (para mostrar al supervisor el viernes)
- **🖨 Acumulado** → `GET /semanas/acumulado/pdf?desde=1&hasta=N&depto=X` — PDF acumulado de todas las semanas del depto

Ambos recargan el CSV guardado y reprocesan con `procesar_fichadas()`. Sin tocar cálculos.

### Separación por departamento en cierre (fix crítico)

`_snapshot_francos_cierre` ahora filtra por legajos del departamento que se cierra.
Antes capturaba francos de todos los deptos que coincidieran en fechas.
Cada cierre graba el nombre del depto en `francos_cierre_detalle.departamento`.

### Actualización automática de saldo_inicial al cerrar período

Al ejecutar `periodo_cerrar`, al final del proceso (después de limpiar sesión y parciales)
se actualiza automáticamente `francos_saldo_inicial` con el saldo neto real del cierre.

**Schema nuevo** (solo ADD COLUMN, no toca datos):

- `francos_saldo_inicial`: `+tomados_al_corte`, `+gen_extra_al_corte`, `+fecha_corte`
- `periodos`: `+saldo_anterior` (JSON para revertir al anular)

**`_calcular_saldos()` actualizado** para usar `fecha_corte` por empleado (en vez de fecha hardcodeada) y netear tomados/gen_extra con sus valores `al_corte`. Para datos existentes (columnas en 0/'2026-05-21') el resultado es idéntico al anterior.

**Reversión**: al anular un cierre (`periodo_anular`), se restauran los saldos anteriores desde `periodos.saldo_anterior`.

### PDF completo de cierre (`_generar_pdf_cierre_completo`)

Botón "📄 Informe completo" en `/periodos/ver/<pid>`.
Ruta: `GET /periodos/<pid>/informe_completo`

Secciones según si el depto tiene fichadas o no:

| Sección | Redes / Admin | Guardias / Internet / Telefonía |
|---|---|---|
| Detalle de horas día a día | ✓ | — |
| Resumen de totales | ✓ | — |
| Saldo de francos al cierre | ✓ | ✓ |
| Detalle de francos tomados | ✓ | ✓ |

Saldo final en verde (>0), rojo (<0), gris (=0). Un departamento por PDF, sin mezcla.

### `pdf_generator.py` — generación en memoria

`generar_pdf_general` y `generar_pdf_resumen` ahora soportan `salida=None` (retornan bytes).
La llamada desde `main.py` (Tkinter) sigue igual — pasa la ruta explícita.

---

## Implementado en sesión julio 2026

### Nuevo departamento: Ingenieros

- Legajos 100 (MANCIONI, Martin) y 101 (GATTI, Marcelo) reasignados de Redes a Ingenieros
- Administrados como `empleados_extra` (sin fichadas biométricas)
- `procesador.py`: nueva constante `LEGAJOS_EXCLUIR_PROCESAMIENTO = {"100", "101"}`; `_df_to_registros()` los filtra antes de procesar
- `_init_db()`: INSERT OR IGNORE + ON CONFLICT UPDATE para mantener nombre y departamento correctos en bases existentes
- `_empleados_conocidos()`: prioriza `empleados_extra` para esos legajos sobre cualquier sesión biométrica

### departamentos.py — normalización centralizada

Nuevo módulo sin dependencias Flask. Expone:
- `clave_canonica(nombre)` — lowercase sin tildes + resolución de alias
- `nombre_visible(nombre)` — nombre oficial con tildes y capitalización
- `mismo_departamento(a, b)` — comparación normalizada
- Alias incluyen "ingenieros" / "ingeniero" / "ingeniros"

### Cierres de francos reversibles

- `cierres_francos` gana columnas: `base_anterior` (JSON snapshot de `francos_saldo_inicial`), `fecha_anulacion`, `motivo_anulacion`, `usuario_anulacion`
- Al crear un cierre: se guarda snapshot en `base_anterior` antes de actualizar saldos
- Nueva ruta `POST /francos/cierre/anular/<cid>`: solo anula el **último cierre activo** del departamento; restaura `francos_saldo_inicial` desde `base_anterior`; desbloquea movimientos vinculados
- El historial muestra `es_ultimo_activo` y `es_reversible` por cierre

### Vinculación de movimientos con cierre

- Nuevas columnas `cierre_francos_id` en `francos_tomados`, `francos_generados`, `francos_semana_manual`
- `francos_tomados` gana también `estado_antes_cierre` (para poder restaurar al anular)
- `_vincular_movimientos_cierre_francos()` asocia movimientos al cerrar; los marca como 'Cerrado'
- Movimientos con `cierre_francos_id IS NOT NULL` están bloqueados: no se pueden eliminar, modificar ni aprobar
- Al anular cierre: `cierre_francos_id` vuelve a NULL, estado restaurado desde `estado_antes_cierre`

### Actualización de planilla Excel desde cierre

- Nueva ruta `POST /francos/planilla/actualizar`: recibe planilla .xlsx + mes (YYYY-MM)
- Requiere cierre activo de Ingenieros Y Guardias en ese mes
- Escribe columna G (Franco Orig.) y H (Franco Tom.) en la hoja del mes (ej: "Julio 2026")
- Usa `openpyxl`; fuerza recalculación de fórmulas al guardar
- `_cierres_francos_del_mes()`: busca el último cierre activo del mes para cada depto exportable

### Estado de confirmaciones agrupado (supervisor.html)

- La tabla de confirmaciones ahora agrupa por Departamento + Semana
- Cabecera por grupo con badge de pendientes
- Empleados ordenados: pendientes primero, luego por legajo

---

## Pendiente

### 1. Reestructuración de UI/layout (alta prioridad)

Objetivo: que la nueva persona que reemplaza a Carola pueda usar la app sola.
Plan acordado:

- Navegación simplificada: 5 secciones con nombres en lenguaje común
- Dashboard de inicio: estado actual por departamento (semáforo verde/amarillo/gris)
- Flujo de carga semanal paso a paso (wizard)
- Textos de ayuda en cada sección
- Fusionar "Historial acumulado" dentro de "Cierre mensual" (misma tabla)
- Mover acciones destructivas a una zona de administración separada

### 2. Módulo de Control de Puntualidad (escritorio Tkinter)

- P1 (DB) y P2 (motor) completados y testeados (63 tests)
- P3 (importador histórico), P4 (UI), P5 (integración main.py pendiente aprobación), P6 (PDF/Excel), P7-P9 pendientes
- **Regla crítica**: nunca tocar main.py, servidor.py, procesador.py, config.json sin aprobación expresa
- Antes de cada bloque: `git diff -- main.py procesador.py pdf_generator.py config.json servidor.py` debe estar vacío

### 3. Botón "Informe mensual completo" (baja prioridad)

Un PDF que combine los cierres de todos los deptos de un mes en un solo archivo,
con salto de página entre departamentos.

### 4. Asignación de horario especial por empleado (Redes)

Extender el formulario web para asignar horario especial a cualquier empleado de Redes
por rango de fechas. La lógica en `obtener_inicio_asignado()` ya soporta esto — falta
UI y persistencia en DB.

---

## Implementado en sesión 21/07/2026 — rediseño de cierre/anulación de francos

A raíz de recuperar un cierre de Administración (fichada mal tipeada, anular
y volver a cerrar) se encontraron y arreglaron 3 bugs reales del mecanismo
`periodos` / `periodo_cerrar` / `periodo_anular` (departamentos **con**
fichadas: Redes, Administración — no confundir con el mecanismo separado
`cierres_francos` de deptos sin fichadas, que no se tocó):

1. **`_snapshot_francos_cierre`** marcaba `francos_tomados.estado='Cerrado'`
   al capturar un franco; `periodo_anular` no lo revertía → francos
   huérfanos excluidos para siempre de cierres futuros. Se agregó
   `_revertir_estado_francos_cierre()`, llamada desde `periodo_anular`.
2. **`/admin/corregir-francos-cierre/<pid>`** calculaba "tomados correcto"
   solo con la ventana de ese cierre puntual, ignorando el acumulado de
   cierres anteriores activos — podía dar saldo de más a un legajo con
   historial previo. Ahora usa una suma acumulada acotada por `fecha_corte`.
   Acepta `?excluir_legajos=` como válvula de escape manual.
3. **La actualización automática de saldo al cerrar** (dentro de
   `periodo_cerrar`) usaba `_calcular_saldos()` — la función de saldo "en
   vivo" para pantalla, que también suma `francos_semana_parcial` de
   cualquier semana/depto en curso sin cerrar — como si fuera el delta
   propio del cierre. Un parcial de otro mes se coló y rompió la cadena de
   saldos. Ahora usa `_delta_francos_cierre(conn, pid, legajos)` (nueva
   función, solo lee `periodo_empleados.francos` y
   `francos_cierre_detalle` de ESE `pid`).

**Regla de oro:** el saldo grabado por un cierre de `periodos` debe poder
recalcularse exactamente igual usando solo `periodo_empleados.francos` +
`francos_cierre_detalle` de ese mismo `periodo_id`. Si algo usa
`_calcular_saldos()` para **grabar** (no para mostrar en pantalla) un saldo,
es un bug.

También se agregó:

- Columna `francos_cierre_detalle.francos_tomados_id` — revertir por id en
  vez de por tupla de campos (legajo/tipo/fechas/días), sin ambigüedad ante
  duplicados exactos.
- `francos_eliminar`/`francos_aprobar` ahora bloquean también francos con
  `estado='Cerrado'` (antes solo chequeaban `cierre_francos_id`, el
  mecanismo hermano).
- `GET /admin/verificar-cadena-saldos-francos` (solo lectura): recorre los
  cierres activos por depto y compara el saldo final recalculado de cada
  uno contra el `saldo_anterior` del siguiente.
- Herramientas manuales de emergencia (`/admin/restaurar-saldo-desde-periodo`,
  `/admin/restaurar-saldo-desde-backup`, `/admin/revertir-francos-cierre-anulado`,
  `/admin/recalcular-horas-cierre`, `/admin/reemplazar-csv-semana`,
  `/admin/semanas-de-periodo`) para corregir un cierre puntual sin anularlo.
- Tests: `tests/test_ciclo_cierre_anular_recerrar_francos.py`.

## Implementado en sesión 31/07/2026 — bug de "Generados" duplicado en saldos (Redes)

Los 27 empleados de Redes mostraban el doble en la columna "Generados" de
`/francos` (ej. Castrillón +6 en vez de +3). Se investigaron y corrigieron
dos causas reales, en dos pasos:

1. **`_calcular_saldos()` leía la tabla-snapshot `francos_semana_parcial`**
   para el "generado del período activo aún sin cerrar" — esa tabla podía
   quedar con filas residuales de semanas ya absorbidas por un cierre.
   Fix: se reemplazó por un cálculo en vivo con `_calcular_periodo()`, la
   misma función que ya usa (y siempre estuvo bien en) la pantalla de
   Períodos — así Saldos y Períodos no pueden desincronizarse. Commit `797ec22`.
2. **Causa real, más profunda**: `_resolver_semana_confirmacion()` reamarra
   por fecha una confirmación archivada de un cierre YA cerrado (no
   anulado) cuando una semana nueva activa se solapa en su rango de fechas
   con ese cierre viejo (ver su docstring y el de `_archivos_confirmacion()`
   — ese mecanismo solo excluye explícitamente a cierres ANULADOS). El día
   quedaba "readoptado" como si fuera del período en curso y `_calcular_periodo()`
   lo volvía a sumar, aunque ya estaba absorbido en el saldo por la
   actualización automática al cerrar. Fix: `_calcular_saldos()` ahora
   cuenta día por día dentro de `gen_parcial` y descarta cualquier franco
   con fecha `<=` al `fecha_corte` de CADA empleado — mismo criterio que ya
   usaba `gen_periodos_por_emp`. Commit `bbbf87c`. Confirmado por la
   usuaria en producción: Castrillón pasó a +3 y el subtotal de Redes dio
   286 (el valor esperado del cierre #4).

Herramienta nueva de diagnóstico (solo lectura, no toca nada):
`GET /admin/desglose-generados/<legajo>` — desglosa componente por
componente de dónde sale "Generados" para un legajo puntual (cada período
cerrado con motivo si no cuenta, lo generado manual, el cálculo en vivo con
detalle de días, y cualquier residuo en `francos_semana_parcial`). Útil para
cualquier futuro reclamo de "el saldo no me cierra" sin tener que adivinar.

**Nota de diseño para el futuro:** el mecanismo de reamarre-por-fecha en
`_resolver_semana_confirmacion()` sigue existiendo — el fix de este
incidente lo neutralizó solo para el cálculo de saldos (filtrando por
`fecha_corte`). Si aparece un síntoma similar (totales de más) en la
pantalla de Períodos o en algún informe que use `_calcular_periodo()`/
`_leer_historial()` directamente, empezar la investigación por ahí.

Tests: `tests/test_ciclo_cierre_anular_recerrar_francos.py` —
`test_calcular_saldos_no_duplica_generados_con_parcial_residual_de_periodo_ya_cerrado`
y `test_calcular_saldos_no_duplica_generados_con_confirmacion_archivada_readoptada_por_fecha`
(este último reproduce el mecanismo real de readopción, no solo residuos de tabla).

El botón "Guardar Franco" del panel supervisor (`/semanas/<n>/guardar-francos`,
`/semanas/guardar-francos-todos`) sigue escribiendo en `francos_semana_parcial`
sin error, pero esa tabla quedó huérfana — ya no la lee ningún cálculo de
saldo, solo las rutas de diagnóstico. Pendiente decidir si se deprecia.

### Seguimiento: el fix de Redes NO cubre a los deptos de cierre manual

El bug de "Generados" duplicado (arriba) es específico del mecanismo
`periodos` (fichadas: Redes, Administración) — depende de
`_resolver_semana_confirmacion()`, que solo existe para deptos con
confirmaciones/tokens. Guardias, Internet, Telefonía e Ingenieros no pasan
por ahí: cargan francos vía `francos_semana_manual`/`francos_generados` y
cierran con el mecanismo separado `cierres_francos`. Ese bug puntual no
puede reproducirse ahí.

Pero se detectó que **`/admin/verificar-cadena-saldos-francos` y
`/admin/auditoria-completa-saldos-francos` excluyen a estos 4 deptos**
(los marcan `no_aplicable` porque solo caminan la cadena de `periodos`) —
nunca hubo forma automática de validar la cadena de cierres manuales.
Se agregó el equivalente:

- `GET /admin/verificar-cadena-cierres-francos` (solo lectura): recorre
  `cierres_francos` ACTIVOS por depto, compara el `saldo_final` guardado en
  `saldo_anterior` de cada cierre contra el `base_anterior` (foto pre-cierre)
  del siguiente, y el último cierre de cada legajo contra
  `francos_saldo_inicial` en vivo. Reporta `desajustes` (huecos reales en la
  cadena) y `no_aplicables` (legajos donde otro mecanismo más reciente tomó
  la posta, ej. volvió a fichadas).
- Pendiente: correrla contra la DB de PythonAnywhere (la local no tiene
  filas en `cierres_francos`) para confirmar si Telefonía tiene un
  desajuste real y, si lo hay, investigar la causa puntual — no asumir que
  es el mismo bug de Redes.

## Implementado en sesión 03/08/2026 — "Generados" tapados por recierre tardío (Administración)

Encontrado revisando trazabilidad de todos los deptos tras el fix de Redes:
GOMEZ MARIO (Administración) generó un franco real el 2026-07-04, visible en
Períodos/Historial, pero **ausente** en "Generados" de la pantalla de
Francos — síntoma inverso al de Redes (acá desaparece, no se duplica).

**Causa raíz:** el cierre #6 de Administración cubría datos hasta
`fecha_hasta` 2026-06-28, pero por haberse anulado y recerrado (incidente ya
documentado arriba, sesión 21/07/2026) terminó de cerrarse recién el
2026-07-20 (`cerrado_en`). `fecha_corte` se fija en `cerrado_en` (la hora
real de cierre, por diseño — ver `admin_corregir_fecha_corte`), no en
`fecha_hasta`. El período siguiente (semanas 1-4, 2026-06-29 al 2026-07-26)
ya se venía cargando en paralelo mientras el cierre #6 seguía sin cerrar, y
generó el franco del 07-04 — anterior a `fecha_corte` (07-20) pero
**posterior** a la ventana real de datos del cierre #6 (que terminaba el
06-28). El filtro de `gen_parcial` en `_calcular_saldos()` (agregado en el
fix de Redes) descartaba cualquier día con `fecha <= fecha_corte` a secas,
sin mirar a qué período pertenecía cada día — tapó el franco nuevo.

**Fix:** `gen_parcial` ahora descarta un día solo si cae dentro de la
ventana `fecha_desde..fecha_hasta` de algún período ACTIVO ya cerrado de
ese legajo (mismos datos que ya usa `gen_periodos_por_emp`), no por estar
antes de `fecha_corte` a secas. Un día de un período todavía abierto nunca
cae dentro de la ventana de un período previo, sin importar cuándo ese
previo terminó de cerrarse en el reloj de pared. Para legajos sin ningún
período cerrado todavía se mantiene la comparación contra `fecha_corte`
como piso (cubre la carga inicial de saldo). Aplicado también en
`/admin/desglose-generados/<legajo>` para que el diagnóstico no quede
inconsistente con lo que muestra Saldos.

Tests: `tests/test_ciclo_cierre_anular_recerrar_francos.py` —
`test_calcular_saldos_no_tapa_franco_del_periodo_abierto_por_recierre_tardio`
(reproduce el incidente real de Gomez Mario). El test de readopción de
Redes (`test_calcular_saldos_no_duplica_generados_con_confirmacion_archivada_readoptada_por_fecha`)
se ajustó para pasarle al período de test una ventana `fecha_desde/fecha_hasta`
realista (antes usaba fechas dummy hardcodeadas en `_crear_periodo`, que no
importaban bajo el filtro viejo pero sí bajo el nuevo).

**No se tocó la lógica de cierre** (`periodo_cerrar`, `francos_cierre_nuevo`,
`_snapshot_francos_cierre`, etc.) — el fix es exclusivamente en cómo
`_calcular_saldos()` lee períodos ya cerrados para la pantalla en vivo.

**Confirmado en producción con `/admin/verificar-cadena-cierres-francos`**:
único desajuste real fue CALVET (Telefonía, legajo 18) — el último cierre
manual (cid=5, 2026-07-08) dejó `saldo_final=8`, pero `francos_saldo_inicial`
en vivo tenía `saldo=7`, sin ningún cierre posterior que lo explique.
Guardias e Internet, con cierres propios en `cierres_francos`, no
mostraron ningún desajuste (su saldo en vivo coincide con su último
cierre). Ingenieros (100/101) salió `no_aplicable` — su saldo fue tocado el
31/07, después del último cierre manual (22/07), por otro mecanismo — no
es un error, solo no verificable con este chequeo puntual.

**Decisión de la usuaria (03/08/2026): no reabrir la causa histórica de
Calvet** ("los cierres anteriores están bien, arranquemos bien desde ahora
con la trazabilidad") — en cambio, foco en (a) corregir el número actual
para que coincida con lo que el cierre ya dejó grabado y (b) que un drift
así no pueda volver a pasar sin dejar rastro. Ver
[[feedback_chequear_trazabilidad_post_cierre]] en memoria.

## Implementado en sesión 03/08/2026 (cont.) — auditoría de `francos_saldo_inicial` + sincronización desde cierre

**Auditoría automática (triggers de SQLite, no instrumentación manual):**
nueva tabla `francos_saldo_inicial_auditoria` + 3 triggers
(`trg_fsi_auditoria_insert/update/delete`) sobre `francos_saldo_inicial`.
Hay ~15 sitios en el código que escriben esa tabla (cierres de los dos
mecanismos, devolución de francos anulados, herramientas de emergencia,
correcciones manuales) — instrumentar cada uno a mano es frágil y un sitio
nuevo se puede olvidar. Un trigger a nivel de base de datos captura
**cualquier** escritura, sin importar el camino, incluida una edición
directa por SQL fuera de la app. Cada fila de auditoría guarda el valor
anterior y nuevo de `saldo`, `tomados_al_corte`, `gen_extra_al_corte`,
`fecha_corte` y `nota`. Consulta: `GET /admin/auditoria-saldo-inicial/<legajo>`.

**Corrección real (no parche puntual en la DB):** nueva ruta
`GET /admin/sincronizar-saldo-inicial-desde-cierre-francos/<cid>` — recalcula
de forma independiente (desde `francos_tomados`/`francos_generados`/
`francos_semana_manual`, acotado a `fecha_hasta`, misma fórmula que
`/admin/recalcular-saldo-cierre-francos`) lo que `francos_saldo_inicial`
debería tener para cada legajo de un cierre manual ya hecho, lo compara
contra el valor en vivo, y con `?confirmar=si` corrige solo los legajos
donde el cierre `cid` sigue siendo el último activo (no pisa un saldo más
nuevo). Dry-run por default, mismo patrón que las demás herramientas de
`/admin/*`. Reemplaza la alternativa de escribir un `UPDATE` manual puntual
para Calvet — cualquier legajo/depto con el mismo síntoma se corrige con la
misma ruta, y queda registrado en `francos_saldo_inicial_auditoria`.

**Bug de migración encontrado y arreglado de paso:** `ALTER TABLE
cierres_francos ADD COLUMN saldo_anterior` se ejecutaba en `_init_db()`
*antes* del `CREATE TABLE IF NOT EXISTS cierres_francos` (más abajo en el
archivo). En producción no se notaba porque el segundo arranque de la app
"autocuraba" (la tabla ya existía la próxima vez), pero en una base nueva
creada de una sola pasada la columna nunca se agregaba. Movido junto a las
otras columnas de `cierres_francos` (`base_anterior`, etc.), que sí estaban
en el orden correcto.

Tests: `tests/test_ciclo_cierre_anular_recerrar_francos.py` —
`test_trigger_auditoria_captura_cualquier_escritura_a_saldo_inicial` (una
escritura por SQL directo, sin pasar por ninguna ruta de la app, queda
igual registrada) y
`test_sincronizar_saldo_inicial_desde_cierre_francos_corrige_drift`
(reproduce el incidente completo de Calvet vía la ruta real
`/francos/cierre/nuevo`, simula el drift externo, y verifica dry-run +
corrección + registro de auditoría).

**Segunda corrección puntual, mismo incidente:** después de arreglar el
`saldo`, Calvet seguía mostrando "+1 Generados" en pantalla. Causa: una
fila en `francos_semana_manual` (mes 2026-05, 1 día, sin `cierre_francos_id`)
nunca absorbida por ningún cierre, que la usuaria confirmó como error de
carga. Se agregó `GET /admin/eliminar-francos-semana-manual/<id>` (dry-run
por default, bloqueada si la fila ya tiene cierre vinculado) y se usó para
borrarla en producción.

### UI: editar/eliminar cargas manuales no cerradas, de cualquier mes

La usuaria señaló el problema de fondo: el formulario de carga semanal en
`/francos` solo permite tocar el **mes actual** — una carga vieja mal hecha
(como la de Calvet) no se podía corregir desde la pantalla normal, había
que pedir una ruta de `/admin/*` cada vez. Implementado en `francos.html` y `servidor.py`:

- `POST /francos/generados/editar/<id>` — corrige días/descripción de un
  franco generado puntual (`francos_generados`) no cerrado. La tabla de
  "Francos generados — Carga manual" en `/francos` ahora tiene un formulario
  inline (días + descripción + Guardar) en vez de solo mostrar el valor.
- `POST /francos/semana-manual/editar/<id>` y
  `POST /francos/semana-manual/eliminar/<id>` — equivalentes para
  `francos_semana_manual`, ambas bloqueadas si `cierre_francos_id` no es
  NULL (igual criterio que todo el resto del proyecto).
- Nueva sección en `/francos`: "Cargas semanales pendientes (todos los
  meses)" — lista TODAS las filas de `francos_semana_manual` con
  `cierre_francos_id IS NULL`, de cualquier mes (no solo el actual), con
  edición inline de días y botón eliminar. La grilla de carga semanal
  original (solo mes actual) queda igual, sin tocar — esta es una sección
  aparte, complementaria.

Con esto, un caso como el de Calvet se puede corregir directamente desde
`/francos` sin pedir ayuda para correr una ruta de admin.

### Auto-verificación de trazabilidad al cerrar (todos los deptos, de ahora en más)

A pedido de la usuaria ("la trazabilidad para los próximos meses de Redes
y Administración y todos"), `/periodo/cerrar` y `/francos/cierre/nuevo`
ahora corren automáticamente, al final, la verificación de cadena
correspondiente y devuelven un campo `"trazabilidad"` en la respuesta
JSON — acotado al departamento que se acaba de cerrar:

- `_verificar_cadena_saldos_francos(conn)` / `_verificar_cadena_cierres_francos(conn)`
  — las rutas de solo lectura `/admin/verificar-cadena-saldos-francos` y
  `/admin/verificar-cadena-cierres-francos` se refactorizaron en estas
  funciones reutilizables; las rutas ahora son wrappers finos.
- `periodo_cerrar` además verifica que **"Generados" quede en 0** para
  cada legajo recién cerrado (todo lo generado hasta el corte ya debería
  estar absorbido en el saldo que se acaba de grabar) — este chequeo corre
  DESPUÉS de que el cierre terminó de guardar, no antes.
- Si `cadena_sana` da `false`, no bloquea el cierre (ya se hizo) — es una
  alerta temprana en la misma respuesta, para no depender de que alguien
  se acuerde de correr las rutas de `/admin/*` por separado el mes que viene.

## Implementado en sesión 04/08/2026 — auditoría de envíos del reporte de saldos

A raíz de una duda de la usuaria ("el viernes pasado mandamos mal los
saldos... ¿te acordás que los corregimos?" — el bug de "Generados"
duplicado de Redes del 31/07/2026, arreglado ese mismo día) se detectó que
**no existía ningún registro de qué se había enviado, a quién, ni
cuándo** — ni en el cron de los viernes (`reporte_saldos_francos.py`,
`_notificar()` solo mostraba un balloon de Windows que no aplica en el
servidor) ni en el botón manual "Enviar" de `/configuracion/email`. Si un
envío salía con datos incorrectos, no había forma de confirmarlo después.

**Fix:** nueva tabla `reportes_enviados` (creada en `_init_db()` y
defensivamente en `_registrar_reporte_enviado()`) con una fila por cada
email realmente enviado: `enviado_en`, `departamentos`, `supervisor_nombre`,
`supervisor_email`, `saldos_snapshot` (JSON — la lista completa de
empleados/saldos tal cual se envió, para reconstruir el contenido exacto
sin adivinar), `origen` (`automatico_viernes` | `manual_boton_enviar`),
`resultado` (`ok` | `error`) y `error_detalle`. Se registra tanto en el
éxito como en el fallo del envío.

`_registrar_reporte_enviado()` vive en `reporte_saldos_francos.py` (import
`reporte_saldos_francos as rrf` ya existía en `servidor.py` para
`supervisores_enviar`) y se llama desde los dos lugares que mandan email:
`reporte_saldos_francos.main()` (cron de los viernes) y
`servidor.supervisores_enviar()` (botón manual).

Consulta de solo lectura: `GET /admin/historial-reportes-enviados`
(filtros opcionales `?supervisor_email=`, `?departamento=`, `?desde=`,
`?resultado=`).

Tests: `tests/test_reporte_saldos_francos.py` —
`test_main_registra_auditoria_de_envios_en_reportes_enviados` y
`test_main_envio_fallido_queda_registrado_como_error`.

## Implementado en sesión 04-05/08/2026 — /historial "Todas" mezclaba meses ya cerrados

Investigando una alarma de la usuaria sobre "Generados" de Redes (que
terminó confirmando, con tres verificaciones independientes —
`/admin/desglose-generados`, `/admin/auditoria-completa-saldos-francos`, y
el propio Historial filtrado por semana puntual — que los números estaban
bien) apareció el verdadero problema: **el filtro "Semana: Todas" de
`/historial` mostraba confirmaciones de meses ya cerrados (junio) mezcladas
con el período activo (julio)**, sin ninguna distinción visual. La usuaria
vio 2 francos de junio de un empleado y los interpretó como parte del
período en curso.

**Causa doble, encontrada en dos pasos:**

1. `historial()` no distinguía "todo el archivo" de "solo lo abierto" —
   pasaba `semana=None` a `_leer_historial()` sin ningún filtro adicional.
2. Al arreglar (1) agregando un post-filtro por semanas activas de
   metadata, un test reveló un bug **preexistente, más profundo**:
   `_leer_historial()` tenía un filtro interno (`semanas_activas`) que
   excluía **cualquier confirmación cuya semana ya no estuviera en
   metadata** — sin importar qué se le pidiera. Esto significaba que
   **elegir un número de semana vieja puntual en el desplegable de
   Historial tampoco funcionaba** (devolvía vacío) una vez que esa semana
   se cerraba y se quitaba de `metadata.json` (`periodo_cerrar` sí la
   quita, ver "Actualizar metadata: solo quitar las semanas cerradas").

**Fix:**

- `_leer_historial()` gana parámetro `incluir_cerradas=False` (default
  preserva el comportamiento de siempre en las demás ~7 llamadas del
  código) que, en `True`, saltea ese filtro interno.
- `historial()`: `semana="archivo_completo"` es una opción NUEVA y
  explícita que trae todo (`incluir_cerradas=True`). El default ("Todas")
  ahora significa **solo las semanas del período activo** (filtradas
  contra `metadata.semanas`, por depto). Elegir una semana puntual vieja
  también usa `incluir_cerradas=True` — ya funciona, cosa que antes no.
- El desplegable de "Semana" en `historial.html` ahora lista *todos* los
  números de semana alguna vez usados (antes solo los del período activo,
  por el mismo bug), y tiene la opción nueva "Ver todo el archivo (incluye
  meses ya cerrados)" al final.

No se tocó `_resolver_semana_confirmacion()` (el mecanismo de readopción
por fecha, ver bug de Redes de julio) ni ningún cálculo de saldo — esto es
puramente sobre qué se **muestra** en la pantalla de Historial.

Test: `tests/test_historial_periodo_activo.py` —
`test_historial_todas_muestra_solo_periodo_activo_no_meses_cerrados`
(reproduce con archivos de confirmación reales el escenario de junio vs.
julio, y verifica las 3 vistas: período activo, archivo completo, y
semana vieja puntual).

## Implementado en sesión 05/08/2026 — mezcla real de Redes/Ingenieros en detalle de francos tomados

La usuaria reportó: "en el detalle de francos tomados me junta los
ingenieros con redes a partir de julio". Esto **sí violaba la regla
número uno del proyecto** (nunca mezclar departamentos) — a diferencia de
las alarmas anteriores de la sesión (que resultaron ser lecturas
correctas de datos reales), acá había una causa de código real.

**Causa raíz:** varias rutas armaban "los legajos de este departamento"
con `SELECT DISTINCT legajo FROM periodo_empleados WHERE departamento=?`
— esa tabla es un **snapshot histórico por cierre que nunca se
actualiza**. Los legajos 100/101 (Mancioni, Gatti) tienen filas viejas ahí
con `departamento='Redes'` de cuando procesaban por fichadas, antes de
pasar a Ingenieros en julio 2026 (ver sección "Nuevo departamento:
Ingenieros" arriba). Esas rutas después traían **todo** `francos_tomados`
de esos legajos —incluida su actividad NUEVA como Ingenieros— y lo
etiquetaban como "Redes". El bug es tan viejo como el traspaso de julio,
pero recién se notó cuando hubo actividad real de Ingenieros para
mostrar.

**Fix:** nueva función `_legajos_actuales_del_depto(departamento)` —
usa `_empleados_conocidos()` (la fuente de verdad vigente, que ya
prioriza `empleados_extra` para 100/101) en vez del snapshot histórico de
`periodo_empleados`. Reemplaza la consulta rota en las 4 rutas que la
tenían:

1. `/francos/pdf_depto` — el bug que reportó la usuaria (detalle de
   francos tomados por depto, sin cierre).
2. `francos_cierre_nuevo` (`POST /francos/cierre/nuevo`) — más grave que
   un problema de display: si alguien elegía "Redes" acá (nada lo
   impedía), el cierre manual iba a vincular y marcar 'Cerrado' la
   actividad de Ingenieros de 100/101 bajo un cierre etiquetado "Redes",
   corrompiendo ambos mecanismos. Se agregó además un guard explícito:
   esta ruta ahora **rechaza** `departamento in ("redes", "administracion")`
   con 400 — esos se cierran únicamente desde Períodos. El selector
   `cf-depto` de `periodos_historial.html` (que antes listaba todos los
   deptos, incluida Redes — ver nota vieja de este archivo) ahora excluye
   Redes/Administración también en el propio `<select>`.
3. `periodos_historial()` — conteo de `total_registros` por cierre manual.
4. `admin_diagnostico_francos()` "Mecanismo B" — agregados por depto.

**No se tocó** ninguna consulta con `periodo_id=?` (esas SÍ deben seguir
siendo el snapshot histórico exacto de ese cierre puntual — `_snapshot_francos_cierre`,
`francos_cierre_detalle`, informe completo de cierre, etc. ya estaban bien,
confirmado por auditoría de código antes de tocar nada).

Tests: `tests/test_no_mezclar_departamentos_legajo_reasignado.py` —
reproduce el estado real (legajo 100 con cierre viejo de Redes +
`empleados_extra` actual como Ingenieros + un franco tomado nuevo) y
verifica que `_legajos_actuales_del_depto`, `/francos/pdf_depto` y el
guard de `/francos/cierre/nuevo` ya no mezclan.

### Informes mensuales combinados filtraban por mes de los datos, no por mes de cierre

En la pantalla "Cierres", los botones "Ver informe mensual combinado" y
"Ver informe mensual de francos (todos los deptos)" (`/periodos/informe_mensual`,
`/periodos/informe_mensual_francos`) filtraban los cierres de `periodos`
por `fecha_desde LIKE '{mes}%'` — el inicio de la ventana de datos que
cubre el cierre. Un cierre recerrado tarde (mismo patrón que el incidente
de Administración del 03/08/2026: datos de junio, `cerrado_en` en julio)
tiene `fecha_desde` de un mes distinto al mes en que se cerró de verdad —
así que al elegir "julio" en el selector, ese cierre de Redes/Administración
no aparecía (reportado por la usuaria: "en este botón verde no parecen
los saldos de redes ni administracion", 05/08/2026).

**Fix:** ambas rutas ahora filtran por `cerrado_en LIKE '{mes}%'` (cuándo
se cerró de verdad), igual criterio que ya usaba el lado de `cierres_francos`
(`fecha_hasta`, más cercano al cierre real que `fecha_desde`). Un cierre
aparece en el mes en que se cerró, no en el mes de los datos que cubre.

Test: `tests/test_informe_mensual_filtra_por_cierre_no_por_datos.py` —
reproduce un cierre con datos de junio y `cerrado_en` de julio, y verifica
que ambos informes lo traen en julio (no en junio).

## Implementado en sesión 07/08/2026 — planilla separada por depto + francos huérfanos en cierre manual

### Planilla Excel de Ingenieros/Guardias: ahora separadas por departamento

Desde julio 2026 la usuaria dejó de usar una única planilla combinada
Ingenieros+Guardias — cada depto tiene su propia planilla Excel. La
herramienta "Actualizar planilla mensual" de `/periodos/historial`
todavía asumía una sola planilla con ambos deptos juntos (`_actualizar_planilla_francos`
recibía el dict `cierres` completo y escribía las dos secciones en el
mismo libro, y la ruta exigía el cierre activo de **ambos** deptos para
actualizar cualquiera de las dos).

**Fix:** `_actualizar_planilla_francos(contenido, mes, departamento, cierre)`
ahora toma un solo departamento y un solo cierre. La UI gana un selector
"Departamento" (Ingenieros/Guardias) junto al mes y el archivo; el
requisito de cierre activo es solo para el depto elegido, no para los
dos. El nombre de archivo descargado incluye el depto.

Tests: `tests/test_actualizar_planilla_francos.py` — actualizado a la
nueva firma, más un test de que actualizar la planilla de un depto ya no
exige el cierre del otro.

### Franco "huérfano": contado en el saldo del cierre pero nunca vinculado (Barolín/Telefonía)

La usuaria notó una inconsistencia real en el cierre #5 de Telefonía
(08/07/2026): el PDF de saldo mostraba "Tomados: 1" para Barolín, pero el
PDF de detalle de francos tomados de ESE MISMO cierre daba `TOTAL: 0` —
el franco #50 (22/06, cargado el 19/06) nunca quedó vinculado
(`cierre_francos_id` seguía `NULL`, estado seguía `'Aprobado'`), aunque
sí bajó el saldo. Revisando el código, el franco cumplía todas las
condiciones de `_vincular_movimientos_cierre_francos` en el momento del
cierre -- no se pudo reconstruir con certeza la causa histórica exacta
sin poder ejecutar consultas forenses contra datos de hace un mes.
Corregido puntualmente con `/admin/vincular-franco-a-cierre/50/5?confirmar=si`
(herramienta que ya existía).

**Prevención ("esto no puede volver a pasar", pedido explícito de la
usuaria):** `francos_cierre_nuevo` ahora compara, para cada legajo, los
días contados en `tomados_al_hasta` (lo que bajó el saldo) contra la
suma real de días vinculados a ese cierre (`francos_tomados` con
`cierre_francos_id` = el cierre recién creado). Si difieren para algún
legajo, queda reportado en un campo nuevo `"francos_huerfanos"` en la
respuesta del cierre — no bloquea el cierre (ya se guardó), es una
alerta temprana para no depender de que alguien lo note comparando dos
PDFs a mano semanas después.

Test: `tests/test_ciclo_cierre_anular_recerrar_francos.py` —
`test_francos_cierre_nuevo_detecta_franco_contado_pero_no_vinculado`
(reproduce el patrón forzando un franco ya `'Cerrado'` de antemano sin
`cierre_francos_id`, que es justo lo que `_vincular_movimientos_cierre_francos`
excluye pero `tomados_al_hasta` no).

### "Generados" fantasma para siempre: franco anterior al primer período conocido (Gomez Mario / Geist Ale)

Mismo día del hallazgo anterior: justo después de cerrar Administración
(período hasta el 02/08), dos legajos (13-GOMEZ MARIO, 11-GEIST ALE)
quedaron con **+1 Generados** en vez de 0. La causa: cada uno tiene un
franco real del **2026-05-02** (sábado) que quedó **fuera de TODAS las
ventanas de período conocidas**, porque el primer período registrado de
ambos arranca el **2026-05-04** — dos días después. El fix del incidente
anterior (comparar contra la ventana de cada período cerrado, en vez de
contra `fecha_corte` a secas) nunca contempló este hueco: un día que no
cae dentro de NINGUNA ventana simplemente nunca se excluye, sin importar
cuántos períodos se cierren después — quedaba sumando +1 "Generados"
fantasma para siempre.

**Fix:** se agregó un piso fijo de arranque del sistema
(`GENESIS_SISTEMA = 2026-05-21`, el mismo valor que ya se usa en toda la
base como default de `fecha_corte`) — cualquier día anterior o igual a
esa fecha se considera absorbido en la carga inicial de saldo, tenga o no
un período que lo cubra. Aplicado en `_calcular_saldos()` y en
`/admin/desglose-generados/<legajo>` (antes de la comparación por
ventana, no en reemplazo de ella).

Pedido explícito de la usuaria tras este hallazgo: verificar en el
momento del cierre que **tanto "Generados" como "Tomados"** queden en 0
para los legajos recién cerrados, en los dos mecanismos (no solo
`periodo_cerrar`, que ya lo hacía solo para generados). Ambas rutas
(`periodo_cerrar` y `francos_cierre_nuevo`) ahora agregan
`"tomados_no_absorbidos"` junto a `"generados_no_absorbidos"` en el campo
`trazabilidad` de la respuesta (matemáticamente "tomados" siempre debería
dar 0 justo después de cerrar, pero se verifica en vez de asumirlo).

Test: `tests/test_ciclo_cierre_anular_recerrar_francos.py` —
`test_calcular_saldos_no_cuenta_franco_anterior_al_primer_periodo_conocido`.

## Implementado en sesión 08/08/2026 — planilla Excel: usar siempre el último cierre activo, no el cierre "del mes"

Después del split por depto (sesión 07/08/2026), la usuaria detectó que
"Actualizar planilla mensual" de Ingenieros **repitió los tomados de
junio** en vez de traer los de julio (4 días de Mancioni + 1 de Gatti
quedaron sin volcar; tuvo que corregir la planilla a mano). Causa:
`_cierres_francos_del_mes(conn, mes)` elegía el cierre cuya `fecha_hasta`
cae en el mes pedido — mismo patrón de bug que el de "informes mensuales
combinados" (sesión 05/08/2026): el cierre real de julio de Ingenieros
tenía `fecha_hasta`/`cerrado_en` que no calzaba con el string `"2026-07"`
esperado, así que la búsqueda por mes no lo encontraba y silenciosamente
devolvía (o reusaba) el cierre de junio.

La usuaria rechazó explícitamente la primera propuesta (agregar un
selector de cierre en la UI para elegir cuál usar) — pidió algo más
simple: **"que lo hagas copiando los tomados del último cierre de
ingenieros, no otro cálculo"**. La planilla no necesita encontrar "el
cierre de este mes": el flujo real es cerrar el depto y enseguida
actualizar su planilla con lo que ese cierre acaba de dejar grabado.

**Fix:** `_cierres_francos_del_mes(conn, mes)` (que buscaba por depto+mes
para Ingenieros y Guardias combinados) fue reemplazada por
`_ultimo_cierre_francos_activo(conn, departamento)` — devuelve el cierre
`ACTIVO` más reciente de ESE departamento por `cerrado_en DESC, id DESC`,
sin ningún filtro de mes. `francos_planilla_actualizar()` ahora llama a
esta función con el depto elegido; "Mes" en el formulario solo controla a
qué pestaña del Excel se escribe (que hoja abrir), no qué cierre se lee.
Mensaje de error actualizado a `"No hay ningún cierre activo de {depto}
todavía."` (antes mencionaba "el mes").

Tests: `tests/test_actualizar_planilla_francos.py` — sin cambios de fondo
en la firma de `_actualizar_planilla_francos` (ya tomaba un cierre
puntual desde el split anterior); se verificó que los 4 tests existentes
siguen pasando con la nueva función de selección.

## Notas importantes

- `sesion.json` y `config_email.json` **no se commitean nunca**
- La DB local y la de PythonAnywhere son **independientes** — siempre verificar contra cuál se opera
- Los backups `backup_*/` son snapshots manuales de sesion.json y semanas, **no tocar**
- El reporte semanal de francos corre en PythonAnywhere (tarea programada); la tarea Windows local está deshabilitada desde 29/05/2026
- Nunca ejecutar `/admin/reset` sin coordinación explícita con el usuario — borra todos los datos
