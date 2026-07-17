# -*- coding: utf-8 -*-
# VERSION ESTABLE - PRUEBA MARZO
# Base corregida con:
# - comparacion habil anterior/siguiente
# - tardanza sin error de entrada_anterior
# - mejor manejo de dyn_start
# Ajuste puntual:
# - soporte de cuadrilla 04:30
# - exclusión de asignaciones especiales de la inferencia grupal
from datetime import datetime, timedelta, time, date
from collections import defaultdict
from pathlib import Path
import sys
import pandas as pd
import json

# Cuando corre como .exe (frozen), config.json vive junto al ejecutable,
# no en el directorio temporal _MEIPASS que PyInstaller usa para el bundle.
if getattr(sys, 'frozen', False):
    CONFIG_PATH = Path(sys.executable).parent / "config.json"
else:
    CONFIG_PATH = Path(__file__).parent / "config.json"

# =========================================================
# CONFIG
# =========================================================
def cargar_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}

def cargar_feriados(config):
    return {
        datetime.strptime(f, "%Y-%m-%d").date()
        for f in config.get("feriados", [])
    }

def cargar_dias_paro(config):
    return {str(f).strip() for f in config.get("dias_paro", []) if str(f).strip()}


# =========================================================
# CONSTANTES
# =========================================================
NORMAL_START = time(6, 0)
OT100_NIGHT_START = time(21, 0)

JORNADA_NORMAL = timedelta(hours=7)

LATE_TOLERANCE_MIN = 6

UMBRAL_1_COMIDA = timedelta(hours=7, minutes=30)
UMBRAL_2_COMIDA = timedelta(hours=14)


# =========================================================
# UTILIDADES
# =========================================================
def normalizar_depto(d):
    return str(d).strip().lower()

def is_weekend(d: date):
    return d.weekday() >= 5

def _fmt(td):
    s = int(td.total_seconds())
    return f"{s//3600:02}:{(s%3600)//60:02}:{s%60:02}"

def _round(td):
    """Redondea un timedelta al número de horas enteras más cercano (umbral: 30 min).
    Convenio Luz y Fuerza: las fracciones de hora se redondean, no se truncan."""
    if td <= timedelta(0):
        return timedelta(0)
    mins = td.total_seconds() / 60
    h = int(mins // 60)
    if mins - h*60 >= 30:
        h += 1
    return timedelta(hours=h)

def cargar_asignaciones_especiales(path: Path = None):
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        return []

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []

    asignaciones = data.get("asignaciones_especiales", [])
    return asignaciones if isinstance(asignaciones, list) else []

def obtener_inicio_asignado(asignaciones, legajo, d):
    """
    Busca asignación especial por legajo y rango de fechas.
    Si existe y tiene inicio válido, devuelve time(HH, MM).
    """
    if not asignaciones:
        return None

    legajo = str(legajo).strip()

    for a in asignaciones:
        if str(a.get("legajo", "")).strip() != legajo:
            continue

        desde_txt = str(a.get("desde", "")).strip()
        hasta_txt = str(a.get("hasta", "")).strip()
        inicio_txt = str(a.get("inicio", "")).strip()

        if not desde_txt or not hasta_txt or not inicio_txt:
            continue

        try:
            desde = datetime.strptime(desde_txt, "%Y-%m-%d").date()
            hasta = datetime.strptime(hasta_txt, "%Y-%m-%d").date()
        except Exception:
            continue

        if not (desde <= d <= hasta):
            continue

        try:
            hh, mm = map(int, inicio_txt.split(":"))
            return time(hh, mm)
        except Exception:
            continue

    return None


# =========================================================
# HORARIOS
# =========================================================
def obtener_horario_fijo(depto, d, config):
    depto = normalizar_depto(depto)
    for h in config.get("horarios_fijos", {}).get(depto, []):
        desde = datetime.strptime(h["desde"], "%Y-%m-%d").date()
        hasta = datetime.strptime(h["hasta"], "%Y-%m-%d").date()
        if desde <= d <= hasta:
            hh, mm = map(int, h["hora"].split(":"))
            return time(hh, mm)
    return None


def obtener_horario_paro(depto, d, config):
    depto = normalizar_depto(depto)
    mapa = config.get("horarios_paro", {}).get(depto)

    if not mapa:
        return None

    if isinstance(mapa, str):
        h, m = map(int, mapa.split(":"))
        return time(h, m)

    clave = f"{d.year}-{d.month:02d}"
    if clave in mapa:
        h, m = map(int, mapa[clave].split(":"))
        return time(h, m)

    return None


def resolver_hora_inicio(d, depto, inicio_grupal, config, es_paro, legajo):
    """Devuelve la hora de inicio que aplica para un empleado en una fecha dada.

    Prioridad: día de paro > horario fijo > cuadrilla inferida > 06:00 por defecto.
    Los días de paro nunca usan cuadrilla ni horario fijo — tienen su propio horario
    para que el cálculo de tardanza sea correcto.
    """
    depto = normalizar_depto(depto)

    # PARO: nunca debe caer en cuadrilla ni en horario fijo.
    # Si no hay horario de paro configurado, por defecto entra a las 06:00.
    if es_paro:
        return obtener_horario_paro(depto, d, config) or NORMAL_START

    # FIJO
    fijo = obtener_horario_fijo(depto, d, config)
    if fijo:
        return fijo

    # CUADRILLA POR LEGAJO
    if (depto, d, legajo) in inicio_grupal:
        return inicio_grupal[(depto, d, legajo)]

    return NORMAL_START


# =========================================================
# CUADRILLA (INFERENCIA)
# =========================================================
def _clasificar_franja_por_minutos(minutos_promedio):
    """
    Clasifica la franja grupal usando puntos medios entre franjas válidas:
    04:30 | 05:00 | 05:30 | 06:00
    """
    if minutos_promedio < 285:    # antes de 04:45
        return time(4, 30)
    elif minutos_promedio < 315:  # 04:45 a 05:14
        return time(5, 0)
    elif minutos_promedio < 345:  # 05:15 a 05:44
        return time(5, 30)
    else:
        return time(6, 0)

# Gatti y Mancioni se gestionan exclusivamente mediante carga manual en el
# departamento Ingenieros. Sus marcas biométricas no deben llegar a ningún
# cálculo, semana, cuadrilla ni cierre automático.
LEGAJOS_EXCLUIR_PROCESAMIENTO = {"100", "101"}
EXCLUIR_DE_INFERENCIA = LEGAJOS_EXCLUIR_PROCESAMIENTO
def inferir_inicio_grupal(registros, asignaciones=None, feriados=None, dias_paro=None, excluir_legajos=None):
    """
    Infiere cuadrilla por departamento y día usando SOLO la primera entrada real
    de cada legajo. Excluye de la inferencia:
      - asignaciones especiales vigentes
      - feriados
      - fines de semana
      - días de paro
    Devuelve {(depto, fecha, legajo): hora_base_grupal}
    """
    por_dia = defaultdict(list)
    primeras_por_legajo = {}
    asignaciones = asignaciones or []
    feriados = feriados or set()
    dias_paro = dias_paro or set()
    excluir_legajos = {str(x).strip() for x in (excluir_legajos or set())}
        
    for depto, legajo, nombre, dt, tipo in registros:
        if tipo != "ENTRADA":
            continue

        depto = normalizar_depto(depto)
        d = dt.date()
        fecha_str = d.strftime("%Y-%m-%d")
        legajo_txt = str(legajo).strip()
        if legajo_txt in excluir_legajos:
            continue

        if is_weekend(d) or d in feriados or fecha_str in dias_paro:
            continue

        if obtener_inicio_asignado(asignaciones, legajo_txt, d):
            continue

        clave = (depto, d, legajo_txt)
        if clave not in primeras_por_legajo or dt < primeras_por_legajo[clave]:
            primeras_por_legajo[clave] = dt

    for (depto, d, legajo), dt in primeras_por_legajo.items():
        por_dia[(depto, d)].append((legajo, dt))

    res = {}

    for (depto, d), entradas in por_dia.items():
        if not entradas:
            continue

        entradas_sorted = sorted(entradas, key=lambda x: x[1])

        grupos = []
        grupo_actual = [entradas_sorted[0]]

        for i in range(1, len(entradas_sorted)):
            prev = entradas_sorted[i - 1][1]
            curr = entradas_sorted[i][1]
            diff = (curr - prev).total_seconds() / 60

            if diff >= 25:
                grupos.append(grupo_actual)
                grupo_actual = []

            grupo_actual.append(entradas_sorted[i])

        grupos.append(grupo_actual)

        for grupo in grupos:
            minutos = [dt.hour * 60 + dt.minute for _, dt in grupo]
            promedio = sum(minutos) / len(minutos)
            hora = _clasificar_franja_por_minutos(promedio)

            for legajo, _ in grupo:
                res[(depto, d, legajo)] = hora

    return res


# =========================================================
# PREPROCESAMIENTO
# =========================================================
def _df_to_registros(df: pd.DataFrame):
    """Convierte el DataFrame del reloj biométrico a lista de tuplas normalizadas.

    Renombra columnas del formato del exportador del reloj, filtra tipos inválidos
    y retorna: [(departamento, legajo, nombre, datetime, tipo), ...]
    Solo se conservan registros de tipo ENTRADA, SALIDA o BREAK.
    """
    df = df.rename(columns={
        "Nro. de usuario": "Legajo",
        "Fecha/Hora": "FechaHora",
        "Tipo de registro": "Tipo"
    })

    cols_min = {"Legajo", "FechaHora", "Tipo"}
    faltan = cols_min - set(df.columns)
    if faltan:
        raise ValueError(f"Faltan columnas requeridas: {faltan}")

    tmp = df.copy()

    tmp["FechaHora"] = pd.to_datetime(tmp["FechaHora"], errors="coerce")
    tmp = tmp.dropna(subset=["FechaHora"]).copy()

    tmp["Legajo"] = tmp["Legajo"].astype(str).str.strip()
    # Excel puede entregar legajos numéricos como "100.0". Se normaliza solo
    # para comparar la exclusión, conservando el valor original de los demás.
    legajos_comparables = tmp["Legajo"].str.replace(r"\.0+$", "", regex=True)
    tmp = tmp[~legajos_comparables.isin(LEGAJOS_EXCLUIR_PROCESAMIENTO)].copy()
    tmp["Tipo"] = tmp["Tipo"].astype(str).str.upper().str.strip()
    tmp = tmp[tmp["Tipo"].isin(["ENTRADA", "SALIDA", "BREAK"])].copy()

    if "Departamento" in tmp.columns:
        tmp["Departamento"] = tmp["Departamento"].fillna("").astype(str).map(normalizar_depto)
    else:
        tmp["Departamento"] = ""

    if "Nombre" in tmp.columns:
        tmp["Nombre"] = tmp["Nombre"].fillna("").astype(str).str.strip()
    else:
        tmp["Nombre"] = tmp["Legajo"]

    tmp = tmp.sort_values(
        ["Departamento", "Legajo", "Nombre", "FechaHora"],
        kind="mergesort"
    )

    return list(zip(
        tmp["Departamento"].tolist(),
        tmp["Legajo"].tolist(),
        tmp["Nombre"].tolist(),
        tmp["FechaHora"].tolist(),
        tmp["Tipo"].tolist()
    ))


def _agrupar_por_empleado(registros):
    """Agrupa registros por (depto, legajo, nombre) y los ordena cronológicamente."""
    grupos = defaultdict(list)

    for depto, legajo, nombre, dt, tipo in registros:
        grupos[(depto, legajo, nombre)].append({
            "dt": dt,
            "tipo": tipo
        })

    for k in grupos:
        grupos[k].sort(key=lambda x: x["dt"])

    return grupos


def _limpiar_y_emparejar(eventos):
    """
    Normaliza eventos y arma pares (entrada, salida).
    Si hay entrada repetida sin salida intermedia,
    se cierra el tramo anterior en la nueva entrada.
    Si queda una entrada abierta al final, se marca incompleta.
    """
    if not eventos:
        return []

    pares = []
    current_in = None

    for ev in eventos:
        tipo = ev["tipo"]
        dt = ev["dt"]

        if tipo == "ENTRADA":
            if current_in is None:
                current_in = dt
            else:
                # tramo incompleto: cerramos con la nueva entrada
                pares.append((current_in, current_in))
                current_in = dt

        elif tipo in ("SALIDA", "BREAK"):
            if current_in is not None:
                pares.append((current_in, dt))
                current_in = None
            else:
                # salida sin entrada previa
                pares.append((dt, dt))

    if current_in is not None:
        pares.append((current_in, current_in))

    return pares


def _debe_imputarse_al_dia_anterior(
    e,
    s,
    depto,
    legajo,
    inicio_grupal,
    asignaciones,
    dias_paro,
    feriados,
    config
):
    """
    Regla puntual y conservadora:
    un tramo de madrugada se imputa al día anterior SOLO si:
    - entrada y salida caen el mismo día de madrugada
    - el día actual NO es feriado, fin de semana ni paro
    - la salida queda al menos 90 minutos antes del inicio asignado o inferido/votado
      de ese mismo día
    """
    if not e or not s:
        return False

    d_actual = e.date()
    fecha_str = d_actual.strftime("%Y-%m-%d")

    if d_actual in feriados or is_weekend(d_actual) or fecha_str in dias_paro:
        return False

    # caso típico: tramo ya dentro de la madrugada del "día siguiente"
    if e.date() != s.date():
        return False

    # solo considerar madrugada; no tocar el resto
    if not (e.time() < time(4, 30) and s.time() < time(4, 30)):
        return False

    inicio_asignado = obtener_inicio_asignado(asignaciones, legajo, d_actual)

    if inicio_asignado:
        inicio_ref = inicio_asignado
    else:
        inicio_ref = resolver_hora_inicio(
            d=d_actual,
            depto=depto,
            inicio_grupal=inicio_grupal,
            config=config,
            es_paro=False,
            legajo=legajo
        )

    inicio_dt = datetime.combine(d_actual, inicio_ref)
    margen_dt = inicio_dt - timedelta(minutes=90)

    return s <= margen_dt


def _calcular_por_dia(
    pares,
    feriados,
    depto,
    inicio_grupal,
    legajo,
    excluir_tardanza,
    asignaciones,
    dias_paro,
    config,
    eventos_dia=None,
    excluir_sa=None
):
    """
    Reglas:
    - Día normal:
        normales + extras
        comidas por tramo
        tardanza sí
    - Paro:
        igual a día normal
        pero sin tardanza
        usando horario base de horarios_paro
    - Feriado / fin de semana:
        todo al 100%
        comidas por total del día
    - Redondeo:
        50 y 100 por separado, al final del día
    """

    por_dia = defaultdict(list)
    for e, s in pares:
        fecha_destino = e.date()

        if _debe_imputarse_al_dia_anterior(
            e=e,
            s=s,
            depto=depto,
            legajo=legajo,
            inicio_grupal=inicio_grupal,
            asignaciones=asignaciones,
            dias_paro=dias_paro,
            feriados=feriados,
            config=config
        ):
            fecha_destino = e.date() - timedelta(days=1)

        por_dia[fecha_destino].append((e, s))

    # Derivar primeras entradas desde por_dia, que ya tiene la imputación
    # de madrugada al día anterior aplicada.  Si usáramos eventos_dia crudos,
    # una entrada de 00:04 del 05/03 seguiría apareciendo bajo esa fecha aunque
    # el tramo ya fue movido al 04/03, desacoplando la lógica de tardanza.
    primeras_entradas = {
        fecha: min(e for e, s in tramos)
        for fecha, tramos in por_dia.items()
        if tramos
    }
    resultados = {}
    excluir_tardanza = excluir_tardanza or set()

    for d in sorted(por_dia):
        tramos = [(a, b) for a, b in por_dia[d]]
        fecha_str = d.strftime("%Y-%m-%d")

        es_paro = fecha_str in dias_paro
        es_feriado = d in feriados
        es_finsem = is_weekend(d)
        es_especial = es_feriado or es_finsem

        if not tramos:
            resultados[d] = {
                "filas": [],
                "totales": {
                    "normales": "00:00:00",
                    "ot50": "00:00:00",
                    "ot100": "00:00:00",
                    "tarde": 0,
                    "franco": 0,
                    "comida": 0
                }
            }
            continue

        inicio_asignado = obtener_inicio_asignado(asignaciones, legajo, d)

        if inicio_asignado:
            dyn_start = inicio_asignado
        else:
            dyn_start = resolver_hora_inicio(
                d=d,
                depto=depto,
                inicio_grupal=inicio_grupal,
                config=config,
                es_paro=es_paro,
                legajo=legajo
            )
        normal_start_dt = datetime.combine(d, dyn_start)
        horario_fin = normal_start_dt + JORNADA_NORMAL
        corte_21 = datetime.combine(d, OT100_NIGHT_START)

        total_norm = timedelta(0)
        total_50 = timedelta(0)
        total_100 = timedelta(0)
        total_tarde = 0
        total_franco = 0
        total_comida = 0
        filas = []

        primer_tramo = tramos[0] if tramos else None

        # =====================================================
        # TARDANZA
        # SOLO PARA DÍAS NORMALES
        # SI HAY INICIO ASIGNADO, USA ESE INICIO
        # SI NO, USA EL INICIO INFERIDO / VOTADO (dyn_start)
        # =====================================================
        if (
            not es_especial
            and not es_paro
            and str(legajo) not in set(map(str, excluir_tardanza))
            and d in primeras_entradas
        ):
            entrada_dia = primeras_entradas[d]
            inicio_referencia = inicio_asignado if inicio_asignado else dyn_start
            inicio_dt = datetime.combine(d, inicio_referencia)
            diff_min = (entrada_dia - inicio_dt).total_seconds() / 60
            total_tarde = 1 if diff_min >= LATE_TOLERANCE_MIN else 0

        # =====================================================
        # MOTOR POR TRAMO
        # =====================================================
        for a_orig, b_orig in tramos:
            obs = []

            if es_feriado:
                obs.append("★ FER")
            elif es_finsem:
                if d.weekday() == 5:
                    obs.append("◆ SAB")
                else:
                    obs.append("◆ DOM")
            elif es_paro:
                obs.append("✦ PARO")

            if inicio_asignado and not es_especial and not es_paro:
                obs.insert(0, "ASIG")

            es_primer_tramo = (a_orig, b_orig) == primer_tramo

            # Tramo incompleto
            if a_orig == b_orig:
                obs.append("△ INC")
                filas.append({
                    "entrada": a_orig,
                    "salida": b_orig,
                    "normales": "00:00:00",
                    "ot50": "00:00:00",
                    "ot100": "00:00:00",
                    "obs": " | ".join(obs)
                })
                continue

            # Feriado / Fin de semana
            if es_especial:
                dur = b_orig - a_orig
                total_100 += dur
                filas.append({
                    "entrada": a_orig,
                    "salida": b_orig,
                    "normales": "00:00:00",
                    "ot50": "00:00:00",
                    "ot100": _fmt(dur),
                    "obs": " | ".join(obs)
                })
                continue

            # Día normal + paro
            if es_primer_tramo and a_orig < normal_start_dt:
                obs.append("↘ EA")

            a_calc = max(a_orig, normal_start_dt)
            b_calc = b_orig

            # Normales: dentro de la jornada
            norm_chunk = max(min(horario_fin, b_calc) - a_calc, timedelta(0))

            # Extras al 50%: desde fin de jornada hasta las 21:00
            inicio_ot50 = max(horario_fin, a_calc)
            ot50 = max(min(b_calc, corte_21) - inicio_ot50, timedelta(0))

            # Extras al 100%: después de las 21:00
            ot100 = max(b_calc - max(a_calc, corte_21), timedelta(0))

            total_norm += norm_chunk
            total_50 += ot50
            total_100 += ot100

            if es_primer_tramo and b_orig < horario_fin and str(legajo) not in (excluir_sa or set()):
                obs.append("✌ SA")

            filas.append({
                "entrada": a_orig,
                "salida": b_orig,
                "normales": _fmt(norm_chunk),
                "ot50": _fmt(ot50),
                "ot100": _fmt(ot100),
                "obs": " | ".join(obs)
            })

        # =====================================================
        # COMIDAS
        # =====================================================
        if es_especial:
            total_trabajado = sum((b - a for a, b in tramos if b > a), timedelta(0))
            if total_trabajado >= UMBRAL_2_COMIDA:
                total_comida = 2
            elif total_trabajado >= UMBRAL_1_COMIDA:
                total_comida = 1
        else:
            for a, b in tramos:
                if b <= a:
                    continue

                a_comida = max(a, normal_start_dt)
                if b <= a_comida:
                    continue

                dur = b - a_comida
                if dur >= UMBRAL_2_COMIDA:
                    total_comida = max(total_comida, 2)
                elif dur >= UMBRAL_1_COMIDA:
                    total_comida = max(total_comida, 1)

        # =====================================================
        # REDONDEO
        # El total diario de extras se redondea UNA sola vez.
        # Ejemplos:
        #   08:30 -> 09:00
        #   08:00 -> 08:00
        # Así evitamos que 50% + 100% superen lo realmente trabajado.
        # =====================================================
        extra_total_real = total_50 + total_100
        extra_total_red = _round(extra_total_real)

        if extra_total_red <= timedelta(0):
            total_50 = timedelta(0)
            total_100 = timedelta(0)
        else:
            # Damos prioridad al 100%, pero sin pasarnos del total redondeado
            total_100_red = min(_round(total_100), extra_total_red)
            total_50_red = extra_total_red - total_100_red

            if total_50_red < timedelta(0):
                total_50_red = timedelta(0)

            total_50 = total_50_red
            total_100 = total_100_red
        
        # =====================================================
        # FRANCO
        # Genera 1 franco solo si es feriado/fin de semana Y trabajó ≥4h.
        # El convenio no genera franco por OT nocturna en día hábil.
        # =====================================================
        if es_especial and total_100 >= timedelta(hours=4):
            total_franco = 1

        # =====================================================
        # BREAK
        # =====================================================
        if eventos_dia:
            hubo_break = any(
                ev["tipo"] == "BREAK" and ev["dt"].date() == d
                for ev in eventos_dia
            )
            if hubo_break and filas:
                if filas[0]["obs"]:
                    filas[0]["obs"] += " | ☕ BRK"
                else:
                    filas[0]["obs"] = "☕ BRK"

        resultados[d] = {
            "filas": filas,
            "totales": {
                "normales": _fmt(total_norm),
                "ot50": _fmt(total_50),
                "ot100": _fmt(total_100),
                "tarde": int(total_tarde),
                "franco": int(total_franco),
                "comida": int(total_comida)
            }
        }

    return resultados


# =========================================================
# API PÚBLICA
# =========================================================
def procesar_fichadas(
    df: pd.DataFrame,
    feriados: set | None = None,
    inicio_variable: dict | None = None,
    excluir_tardanza: set | None = None,
    excluir_sa: set | None = None
):
    """
    Procesa un DataFrame de fichadas y devuelve estructura por empleado.

    Parámetros:
    - df: DataFrame con fichadas
    - feriados: set opcional de date; si no viene, se toma de config
    - inicio_variable: reservado para futura extensión
    - excluir_tardanza: set de legajos a excluir de cálculo de tardanza
    """
    config = cargar_config()

    if feriados is None:
        feriados = cargar_feriados(config)

    inicio_variable = inicio_variable or {}
    excluir_tardanza = excluir_tardanza or set()
    asignaciones = cargar_asignaciones_especiales()
    dias_paro = cargar_dias_paro(config)

    registros = _df_to_registros(df)
    grupos = _agrupar_por_empleado(registros)

    # inferencia de cuadrilla usando el universo de entradas,
    # excluyendo especiales, feriados, fines de semana y paro
    inicio_grupal = inferir_inicio_grupal(
        registros,
        asignaciones=asignaciones,
        feriados=feriados,
        dias_paro=dias_paro,
        excluir_legajos=EXCLUIR_DE_INFERENCIA
    )

    resultados = {}

    for key, eventos in grupos.items():
        depto, legajo, nombre = key

        pares = _limpiar_y_emparejar(eventos)

        por_dia = _calcular_por_dia(
            pares=pares,
            feriados=feriados,
            depto=depto,
            inicio_grupal=inicio_grupal,
            legajo=legajo,
            excluir_tardanza=excluir_tardanza,
            asignaciones=asignaciones,
            dias_paro=dias_paro,
            config=config,
            eventos_dia=eventos,
            excluir_sa=excluir_sa
        )

        resultados[key] = por_dia

    return resultados


# =========================================================
# SALIDA APLANADA POR TRAMO
# =========================================================
def aplanar_registros_por_tramo(resultados):
    """
    Convierte la estructura procesada en una salida lista para exportar,
    manteniendo una fila por tramo y poniendo los totales del día
    solamente en la primera fila de cada fecha.
    """
    salida = []

    for (depto, legajo, nombre), por_dia in resultados.items():
        filas_emp = []

        for d in sorted(por_dia.keys()):
            data_dia = por_dia[d]
            tramos = data_dia.get("filas", [])
            tot = data_dia.get("totales", {})

            norm_dia = tot.get("normales", "00:00:00")
            ot50_dia = tot.get("ot50", "00:00:00")
            ot100_dia = tot.get("ot100", "00:00:00")
            comida_dia = int(tot.get("comida", 0))
            franco_dia = int(tot.get("franco", 0))
            tarde_dia = int(tot.get("tarde", 0))

            if not tramos:
                filas_emp.append({
                    "Fecha": d.strftime("%Y-%m-%d"),
                    "Entrada": "",
                    "Salida": "",
                    "Normales": norm_dia,
                    "50%": ot50_dia,
                    "100%": ot100_dia,
                    "Tarde": tarde_dia,
                    "FRANCO": franco_dia,
                    "COMIDA": comida_dia,
                    "Observaciones": ""
                })
                continue

            for idx, fila in enumerate(tramos):
                primera = idx == 0

                filas_emp.append({
                    "Fecha": d.strftime("%Y-%m-%d"),
                    "Entrada": fila["entrada"].strftime("%H:%M:%S") if fila.get("entrada") else "",
                    "Salida": fila["salida"].strftime("%H:%M:%S") if fila.get("salida") else "",
                    "Normales": norm_dia if primera else "00:00:00",
                    "50%": ot50_dia if primera else "00:00:00",
                    "100%": ot100_dia if primera else "00:00:00",
                    "Tarde": tarde_dia if primera else 0,
                    "FRANCO": franco_dia if primera else 0,
                    "COMIDA": comida_dia if primera else 0,
                    "Observaciones": fila.get("obs", "") if primera else ""
                })

        salida.append({
            "departamento": depto,
            "legajo": legajo,
            "nombre": nombre,
            "registros": filas_emp
        })

    return salida


# =========================================================
# UTILIDAD OPCIONAL: A DATAFRAME
# =========================================================
def aplanar_a_dataframe(resultados):
    """
    Devuelve un DataFrame plano útil para exportar a Excel.
    """
    filas = []

    for emp in aplanar_registros_por_tramo(resultados):
        depto = emp["departamento"]
        legajo = emp["legajo"]
        nombre = emp["nombre"]

        for r in emp["registros"]:
            filas.append({
                "Departamento": depto,
                "Legajo": legajo,
                "Nombre": nombre,
                "Fecha": r["Fecha"],
                "Entrada": r["Entrada"],
                "Salida": r["Salida"],
                "Normales": r["Normales"],
                "50%": r["50%"],
                "100%": r["100%"],
                "Tarde": r["Tarde"],
                "FRANCO": r["FRANCO"],
                "COMIDA": r["COMIDA"],
                "Observaciones": r["Observaciones"]
            })

    return pd.DataFrame(filas)
