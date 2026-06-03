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
- **Venv:** `.venv/Scripts/python.exe` (local Windows)

---

## Producción

- **URL:** https://cmhoras.pythonanywhere.com
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
| `pdf_generator.py` | Genera PDFs de liquidación por empleado y resumen consolidado |
| `reporte_saldos_francos.py` | Genera PDF de saldos de francos por depto y los envía por email |
| `main.py` | App Tkinter: carga fichadas, llama al procesador, genera PDFs, gestiona semanas |
| `feriados_gui.py` | Ventana Tkinter para gestionar feriados en config.json |
| `graficos_ui.py` | Panel Tkinter con gráficos estadísticos de horas extras |
| `resumen_ui.py` | Pantalla Tkinter de resumen consolidado |
| `horarios_paro.py` | Helpers para leer/guardar horarios de días de paro |

---

## Flujo de datos

```
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
| `francos_tomados` | Francos tomados: legajo, tipo (UNICO/RANGO/SUELTAS), fecha_desde, fecha_hasta, fechas_sueltas, dias, estado, observaciones |
| `francos_saldo_inicial` | Saldo inicial cargado al 04/05/2026 (ajustado 21/05/2026 para Redes y Guardias) |
| `francos_generados` | Francos generados manualmente para deptos sin fichadas |
| `francos_semana_manual` | Francos semanales de Guardias/Internet/Telefonía cargados desde el formulario web |
| `francos_semana_parcial` | Snapshot del período activo guardado cada viernes (borrado al cerrar el período) |
| `francos_cierre_detalle` | Copia de francos_tomados al momento de cada cierre (historial inmutable) |
| `supervisores` | nombre, email, departamentos (JSON array), activo |
| `empleados_extra` | Empleados de deptos sin fichadas: Guardias, Internet, Telefonía + Karen Soto (Redes) |

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

```
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

| Depto | Fichadas | Carga manual | Horario variable |
|---|---|---|---|
| Redes | Sí (biométrico) | No | Sí — varía verano/invierno |
| Administración | Sí (biométrico) | No | No |
| Guardias | No | Semanal desde formulario web | No |
| Internet | No | Semanal desde formulario web | No |
| Telefonía | No | Semanal desde formulario web | No |

Los deptos sin fichadas (Guardias, Internet, Telefonía) tienen empleados en
`empleados_extra` y francos generados en `francos_semana_manual` + `francos_generados`.

---

## Empleados extra cargados (21/05/2026)

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
| GET | `/semanas/<n>/pdf` | `semana_pdf(n)` | **PDF detallado día a día** de la semana N (para el supervisor) |
| GET | `/semanas/acumulado/pdf` | `semanas_acumulado_pdf()` | **PDF acumulado** de varias semanas; params: `desde`, `hasta`, `depto` |
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
| GET | `/periodos/francos_pdf/<pid>` | `periodos_francos_pdf(pid)` | Descarga PDF de francos tomados del cierre |
| GET | `/periodos/confirmaciones_pdf/<pid>` | `periodos_confirmaciones_pdf(pid)` | Descarga PDF de confirmaciones archivadas del cierre |
| POST | `/periodos/anular/<pid>` | `periodo_anular(pid)` | Anula un cierre (estado ANULADO); requiere motivo |
| GET | `/francos` | `francos()` | Gestión de francos tomados: tabla de saldos + registrar nuevo |
| POST | `/francos/nuevo` | `francos_nuevo()` | Registra nuevo franco tomado; valida solapamiento |
| POST | `/francos/modificar/<fid>` | `francos_modificar(fid)` | Modifica franco existente |
| POST | `/francos/eliminar/<fid>` | `francos_eliminar(fid)` | Elimina franco tomado |
| GET | `/francos/saldos` | `francos_saldos()` | Saldos actuales de francos por empleado (JSON) |
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
| `_empleados_conocidos()` | Lista deduplicada desde `empleados_extra` + `periodo_empleados` + sesión |
| `_aplicar_exclusiones_ot(empleados)` | Marca empleados como `excluido_ot` |
| `_es_guardias(conn, legajo)` | Verifica si el empleado pertenece a GUARDIAS |
| `_validar_franco_nuevo(conn, leg, tipo, fd, fh, fechas_sueltas, exclude_id)` | Valida fechas hábiles y no-solapamiento |
| `_fechas_del_registro(tipo, fd, fh, fechas_sueltas, feriados)` | Resuelve fechas efectivas según tipo de franco |
| `_dias_habiles(fd, fh)` | Cuenta días hábiles entre fechas excluyendo feriados |
| `_fechas_habiles_set(desde, hasta, feriados)` | Retorna conjunto de dates hábiles |
| `_cargar_feriados_config()` | Lee feriados desde `config.json` |

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

| Función | Qué hace |
|---|---|
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
| `inferir_inicio_grupal(registros, asignaciones, feriados, dias_paro, excluir_legajos)` | **Núcleo de cuadrilla**: infiere hora de entrada grupal por depto+fecha |
| `_df_to_registros(df)` | Convierte DataFrame a tuplas (depto, legajo, nombre, datetime, tipo) |
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
- Legajos siempre como `str` para comparaciones (pueden tener ceros a la izquierda)
- Departamentos: minúsculas en `procesador.py`, mayúsculas en vistas web
- `_normalizar_departamento_web()` antes de cualquier comparación por depto en el servidor

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

## Features pendientes

### Asignación de horario especial por empleado (Redes)
Extender el formulario web para que el supervisor asigne horario especial a cualquier
empleado de Redes por rango de fechas. La lógica en `obtener_inicio_asignado()` ya
soporta esto — falta UI y persistencia en DB (hoy solo existe para Karen Soto en
`config.json → asignaciones_especiales`).

### Reestructuración de UI/layout
Pendiente: revisar flujo de pantallas, hacer la interfaz más intuitiva y bien explicada.
Ver discusión en issue / historial de conversación con Carola Martin.

---

## Notas importantes

- `sesion.json` y `config_email.json` **no se commitean nunca**
- La DB local y la de PythonAnywhere son **independientes** — siempre verificar contra cuál se opera
- Los backups `backup_*/` son snapshots manuales de sesion.json y semanas, **no tocar**
- El reporte semanal de francos corre en PythonAnywhere (tarea programada); la tarea Windows local está deshabilitada desde 29/05/2026
- Nunca ejecutar `/admin/reset` sin coordinación explícita con el usuario — borra todos los datos
