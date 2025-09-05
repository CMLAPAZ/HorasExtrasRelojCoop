# -*- coding: utf-8 -*-
"""
Módulo: procesador.py
Autor: Carola + ChatGPT
Descripción:
------------
Procesa fichadas de empleados a partir de un DataFrame y calcula:
- Horas normales
- Horas extra al 50% y al 100%
- Comidas
- Francos compensatorios
- Llegadas tarde
- Observaciones (feriado, fin de semana, salida anticipada, etc.)

Los feriados se cargan automáticamente desde el archivo config.json si no se
pasan explícitamente como parámetro.
"""

from datetime import datetime, timedelta, time, date
from collections import defaultdict
import pandas as pd
import json
from pathlib import Path

# ---------------- Constantes ----------------
TIME_FMT = "%Y-%m-%d %H:%M:%S"
DATE_FMT = "%Y-%m-%d"

NORMAL_START = time(6, 0, 0)            # Inicio jornada
NORMAL_END = time(13, 0, 0)            # Fin jornada normal
OT100_NIGHT_START = time(21, 0, 0)     # Inicio horas 100% nocturnas
LATE_LIMIT = time(6, 6, 0)             # Límite de llegada tarde

UMBRAL_1_COMIDA = timedelta(hours=7, minutes=30)
UMBRAL_2_COMIDA = timedelta(hours=15, minutes=0)

# ------------------- FERIADOS -------------------
# Por defecto, busca config.json en la misma carpeta que este archivo.
CONFIG_PATH = Path(__file__).parent / "config.json"


def _parse_date_string(s):
    """Intenta parsear una string a date probando varios formatos comunes."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    formatos = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y%m%d")
    for fmt in formatos:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    # Intento parseo ISO (datetime con hora o fecha)
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        pass
    # Heurística final para entradas raras (ej. dd-mm-yyyy sin ceros)
    try:
        parts = [p for p in (s.replace("/", "-").split("-")) if p]
        if len(parts) >= 3:
            p0, p1, p2 = parts[0], parts[1], parts[2]
            if len(p0) == 4:
                cand = f"{p0}-{p1.zfill(2)}-{p2.zfill(2)}"
            else:
                cand = f"{p2.zfill(4)}-{p1.zfill(2)}-{p0.zfill(2)}"
            return datetime.strptime(cand, "%Y-%m-%d").date()
    except Exception:
        pass
    return None


def cargar_feriados(path: Path = None, verbose: bool = False):
    """
    Carga feriados desde JSON.
    Acepta claves: "feriados", "holidays", "dias_especiales", "diasEspeciales".
    También acepta:
      - JSON que es directamente una lista: ["2025-08-17", "25/12/2025"]
      - JSON dict con keys como fechas: { "2025-08-17": "Feriado" }
    Devuelve un set de objetos date.
    """
    p = Path(path) if path else CONFIG_PATH

    # Si no existe en la ruta del módulo, intentar cwd/config.json
    if not p.exists():
        alt = Path.cwd() / p.name
        if alt.exists():
            p = alt

    if verbose:
        print(f"[DEBUG] cargar_feriados() buscando archivo en: {p} (exists={p.exists()})")
        print(f"[DEBUG] cwd = {Path.cwd()}")

    if not p.exists():
        if verbose:
            print(f"[WARN] No se encontró {p}. Retornando set vacío.")
        return set()

    try:
        raw_text = p.read_text(encoding="utf-8")
    except Exception as e:
        if verbose:
            print(f"[ERROR] No pude leer {p}: {e}")
        return set()

    try:
        data = json.loads(raw_text)
    except Exception as e:
        if verbose:
            print(f"[ERROR] JSON inválido en {p}: {e}")
        return set()

    raw = []
    # Buscar claves comunes
    for key in ("feriados", "holidays", "dias_especiales", "diasEspeciales"):
        if isinstance(data, dict) and key in data and isinstance(data[key], list):
            raw = data[key]
            break

    # Si el JSON es directamente una lista
    if not raw and isinstance(data, list):
        raw = data

    # Si es un dict y sus keys parecen fechas, tomar las keys
    if not raw and isinstance(data, dict):
        posibles = list(data.keys())
        fecha_ok = 0
        for k in posibles[:20]:
            if _parse_date_string(k):
                fecha_ok += 1
        if fecha_ok >= 1:
            raw = posibles

    holidays = set()
    for item in raw:
        d = _parse_date_string(item)
        if d:
            holidays.add(d)
        else:
            if verbose:
                print(f"[WARN] No pude parsear entrada de feriados: {item}")

    if verbose:
        print(f"[INFO] Feriados cargados: {len(holidays)} -> {sorted([x.isoformat() for x in holidays])}")

    return holidays


# --------------- Utilidades -----------------
def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def clamp_interval(a: datetime, b: datetime, w_start: datetime, w_end: datetime) -> timedelta:
    start = max(a, w_start)
    end = min(b, w_end)
    return max(end - start, timedelta(0))


def _round_to_hour(td: timedelta) -> timedelta:
    if not isinstance(td, timedelta) or td <= timedelta(0):
        return timedelta(0)
    total_min = td.total_seconds() / 60.0
    hours = int(total_min // 60)
    rem = total_min - hours * 60
    if rem >= 30:
        hours += 1
    return timedelta(hours=hours)


def _fmt(td: timedelta) -> str:
    if not isinstance(td, timedelta):
        return "00:00:00"
    total_seconds = int(td.total_seconds())
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02}:{m:02}:{s:02}"


# ----------- Preprocesamiento DF ------------
def _df_to_registros(df: pd.DataFrame):
    renombres = {
        "Nro. de usuario": "Legajo",
        "Fecha/Hora": "FechaHora",
        "Tipo de registro": "Tipo"
    }
    df = df.rename(columns=renombres)

    cols_min = {"Legajo", "FechaHora", "Tipo"}
    if not cols_min.issubset(df.columns):
        faltan = cols_min - set(df.columns)
        raise ValueError(f"Faltan columnas requeridas: {faltan}")

    tmp = df.copy()
    tmp["FechaHora"] = pd.to_datetime(tmp["FechaHora"], errors="coerce")
    tmp = tmp[~tmp["FechaHora"].isna()].copy()
    tmp["Legajo"] = tmp["Legajo"].astype(str).str.strip()
    tmp["Tipo"] = tmp["Tipo"].fillna("").astype(str).str.upper().str.strip()

    if "Nombre" in tmp.columns:
        tmp["Nombre"] = tmp["Nombre"].ffill().fillna("").astype(str).str.strip()
    else:
        tmp["Nombre"] = tmp["Legajo"]

    if "Departamento" in tmp.columns:
        tmp["Departamento"] = tmp["Departamento"].ffill().fillna("").astype(str).str.strip()
    else:
        tmp["Departamento"] = ""

    tmp = tmp[tmp["Tipo"].isin(["ENTRADA", "SALIDA", "BREAK"])].copy()
    tmp.sort_values(["Departamento", "Legajo", "Nombre", "FechaHora"], inplace=True, kind="mergesort")

    return list(zip(
        tmp["Departamento"].tolist(),
        tmp["Legajo"].tolist(),
        tmp["Nombre"].tolist(),
        tmp["FechaHora"].to_list(),
        tmp["Tipo"].tolist()
    ))


def _agrupar_por_empleado(registros):
    grupos = defaultdict(list)
    for depto, legajo, nombre, dt, tipo in registros:
        grupos[(depto, legajo, nombre)].append({"dt": dt, "tipo": tipo})
    for k in grupos:
        grupos[k].sort(key=lambda x: x["dt"])
    return grupos


def _limpiar_y_emparejar(eventos):
    """
    Normaliza eventos, elimina rebotes ENTRADA->ENTRADA < 2min, reordena SALIDA/ENTRADA mal ordenados
    y devuelve lista de pares (entrada, salida) como datetimes.
    """
    if not eventos:
        return []
    limpios = []
    last_in = None
    for ev in eventos:
        if ev["tipo"] == "ENTRADA":
            if last_in and (ev["dt"] - last_in).total_seconds() < 120:
                # rebote de entrada muy corto -> ignorar
                continue
            last_in = ev["dt"]
            limpios.append(ev)
        elif ev["tipo"] in ["SALIDA", "BREAK"]:
            limpios.append(ev)

    corr = []
    for ev in limpios:
        if corr and corr[-1]["tipo"] == "SALIDA" and ev["tipo"] == "ENTRADA":
            # si SALIDA seguido de ENTRADA y están desordenados por timestamp, intercambiar
            if ev["dt"] < corr[-1]["dt"]:
                corr[-1], ev = ev, corr[-1]
        corr.append(ev)

    pares = []
    current_in = None
    for ev in corr:
        if ev["tipo"] == "ENTRADA":
            if current_in is None:
                current_in = ev["dt"]
            else:
                # entrada seguida de entrada -> asumimos cierre del tramo anterior con esta entrada
                pares.append((current_in, ev["dt"]))
                current_in = ev["dt"]
        elif ev["tipo"] == "SALIDA":
            if current_in is not None:
                pares.append((current_in, ev["dt"]))
                current_in = None
    return pares


def _partir_tramo(e: datetime, s: datetime):
    """
    Si el tramo cruza de fecha, lo parte en subtramos por día.
    Devuelve lista de (fecha, inicio, fin).
    """
    if e.date() == s.date():
        return [(e.date(), e, s)]
    parts = []
    cur_start = e
    while cur_start.date() < s.date():
        end_of_day = datetime.combine(cur_start.date(), time(23, 59, 59))
        parts.append((cur_start.date(), cur_start, end_of_day))
        cur_start = datetime.combine(cur_start.date() + timedelta(days=1), time(0, 0, 0))
    parts.append((s.date(), cur_start, s))
    return parts


# ----------- Cálculo por día ----------------
def _calcular_por_dia(pares, feriados_set, eventos_dia):
    """
    pares: lista de (datetime entrada, datetime salida)
    feriados_set: set de date objects
    eventos_dia: lista original de eventos para este empleado (se usa para detectar BREAK)
    """
    por_dia = defaultdict(list)
    for e, s in pares:
        for d, a, b in _partir_tramo(e, s):
            por_dia[d].append((a, b))

    resultados = {}
    for d in sorted(por_dia.keys()):
        tramos = sorted(por_dia[d], key=lambda x: x[0])

        es_feriado = (feriados_set is not None) and (d in feriados_set)
        es_finsem = is_weekend(d)
        es_especial = es_feriado or es_finsem

        filas = []
        total_norm = timedelta(0)
        total_50 = timedelta(0)
        total_100 = timedelta(0)
        total_tarde = 0
        total_franco = 0
        total_comida = 0

        # Llegada tarde se evalúa solo en días hábiles (no feriado/fin de semana)
        if tramos and (not es_especial) and tramos[0][0].time() >= LATE_LIMIT:
            total_tarde = 1

        normal_consumida = False
        for (a, b) in tramos:
            obs = []
            if es_feriado:
                obs.append("Feriado ✦")
            if es_finsem and not es_feriado:
                obs.append("Sábado" if d.weekday() == 5 else "Domingo")

            if not es_especial:
                # Descontar minutos anteriores a la jornada en días hábiles
                if a.date() == d and a.time() < NORMAL_START:
                    a = datetime.combine(d, NORMAL_START)

                # calcular normales solo una vez por día en el primer tramo que aplique
                if not normal_consumida:
                    norm = clamp_interval(a, b,
                                          datetime.combine(d, NORMAL_START),
                                          datetime.combine(d, NORMAL_END))
                    total_norm += norm
                    normal_consumida = norm > timedelta(0)
                else:
                    norm = timedelta(0)

                dur_total = b - a
                ot50 = clamp_interval(a, b,
                                      datetime.combine(d, NORMAL_END),
                                      datetime.combine(d, OT100_NIGHT_START))
                ot100 = timedelta(0)
                if b > datetime.combine(d, OT100_NIGHT_START):
                    ot100 = b - max(a, datetime.combine(d, OT100_NIGHT_START))

                # ajusta solapamientos con dur_total por seguridad
                if ot50 + ot100 > dur_total:
                    exceso = (ot50 + ot100) - dur_total
                    if ot50 >= exceso:
                        ot50 -= exceso
                    else:
                        exceso -= ot50
                        ot50 = timedelta(0)
                        ot100 -= exceso

                total_50 += ot50
                total_100 += ot100

            else:
                # en feriados/fin de semana todo va al 100% (si el tramo pertenece a ese día)
                if a.date() == d:
                    dur = b - a
                    norm = timedelta(0)
                    ot50 = timedelta(0)
                    ot100 = dur
                    total_100 += dur
                else:
                    # tramo que empieza en día anterior y termina en este feriado -> ya fue tratado en su día correcto
                    continue

            if b.time() < NORMAL_END and not es_especial:
                obs.append("Salida anticipada")

            filas.append({
                "entrada": a, "salida": b,
                "normales": _fmt(norm), "ot50": _fmt(ot50), "ot100": _fmt(ot100),
                "tarde": 0, "franco": 0, "comida": 0,
                "obs": ", ".join(obs)
            })

        # ---- cálculo de comidas por día ----
        total_comida = 0

        if es_especial:
            # En sábados/domingos/feriados: la regla se aplica sobre la suma TOTAL
            # de horas trabajadas en el día (incluye tramos discontinuos).
            total_trabajado = timedelta(0)
            for a, b in tramos:
                inicio = a
                fin = b
                # contar solo la porción del tramo que pertenece a este día
                if inicio.date() < d:
                    inicio = datetime.combine(d, time(0, 0, 0))
                if fin.date() > d:
                    fin = datetime.combine(d, time(23, 59, 59))
                if fin > inicio:
                    total_trabajado += (fin - inicio)

            if total_trabajado >= UMBRAL_2_COMIDA:
                total_comida = 2
            elif total_trabajado >= UMBRAL_1_COMIDA:
                total_comida = 1
        else:
            # Día hábil: comportamiento por tramo (no sumar discontinuos)
            for a, b in tramos:
                dur = b - a
                if a.date() == d and a.time() < NORMAL_START:
                    a = datetime.combine(a.date(), NORMAL_START)
                    dur = b - a
                if dur >= UMBRAL_2_COMIDA:
                    total_comida = max(total_comida, 2)
                elif dur >= UMBRAL_1_COMIDA:
                    total_comida = max(total_comida, 1)

        total_50_rounded = _round_to_hour(total_50)
        total_100_rounded = _round_to_hour(total_100)

        # ---- Franco ----
        # Si es día especial (feriado o fin de semana) y total 100% redondeado >= 4h -> franco
        if es_especial and total_100_rounded >= timedelta(hours=4):
            total_franco = 1
            if filas:
                filas[-1]["franco"] = 1
                if filas[-1]["obs"]:
                    filas[-1]["obs"] += " | Franco compensatorio"
                else:
                    filas[-1]["obs"] = "Franco compensatorio"

        # ---- Break detectado en eventos originales ----
        if any(ev["tipo"] == "BREAK" and ev["dt"].date() == d for ev in eventos_dia):
            if filas:
                if filas[0]["obs"]:
                    filas[0]["obs"] += " | Break registrado ✌️"
                else:
                    filas[0]["obs"] = "Break registrado ✌️"

        resultados[d] = {
            "filas": filas,
            "totales": {
                "normales": _fmt(total_norm),
                "ot50": _fmt(total_50_rounded),
                "ot100": _fmt(total_100_rounded),
                "tarde": int(total_tarde),
                "franco": int(total_franco),
                "comida": int(total_comida)
            }
        }
    return resultados


# ---------- API pública ----------
def procesar_fichadas(df: pd.DataFrame, feriados: set = None):
    """
    Procesa un DataFrame de fichadas y devuelve estructura por empleado.
    Si feriados es None, se cargan automáticamente desde config.json.
    """
    if feriados is None:
        feriados = cargar_feriados()

    registros = _df_to_registros(df)
    grupos = _agrupar_por_empleado(registros)
    resultados = {}
    for key, eventos in grupos.items():
        pares = _limpiar_y_emparejar(eventos)
        por_dia = _calcular_por_dia(pares, feriados, eventos)
        resultados[key] = por_dia
    return resultados


def aplanar_registros_por_tramo(resultados: dict):
    salida = []
    for (depto, legajo, nombre), por_dia in resultados.items():
        filas_emp = []
        for d in sorted(por_dia.keys()):
            data_dia = por_dia[d]
            tramos = data_dia.get("filas", [])

            norm_dia = data_dia["totales"]["normales"]
            ot50_dia = data_dia["totales"]["ot50"]
            ot100_dia = data_dia["totales"]["ot100"]
            comida_dia = data_dia["totales"]["comida"]
            franco_dia = data_dia["totales"]["franco"]
            tarde_dia = data_dia["totales"]["tarde"]

            for idx, fila in enumerate(tramos):
                primera = (idx == 0)
                filas_emp.append({
                    "Fecha": d.strftime(DATE_FMT),
                    "Entrada": fila["entrada"].strftime("%H:%M:%S"),
                    "Salida": fila["salida"].strftime("%H:%M:%S"),

                    "Normales": str(norm_dia) if primera else "00:00:00",
                    "50%": str(ot50_dia) if primera else "00:00:00",
                    "100%": str(ot100_dia) if primera else "00:00:00",

                    "Tarde": int(tarde_dia) if primera else 0,
                    "FRANCO": int(franco_dia) if primera else 0,
                    "COMIDA": int(comida_dia) if primera else 0,

                    "Observaciones": fila["obs"] if primera else ""
                })
        salida.append({
            "depto": depto,
            "legajo": legajo,
            "nombre": nombre,
            "registros": filas_emp
        })
    return salida


