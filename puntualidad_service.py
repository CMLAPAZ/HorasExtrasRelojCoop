# -*- coding: utf-8 -*-
"""
puntualidad_service.py — Motor de cálculo de Control de Puntualidad.

Exclusivo de la aplicación de escritorio local (Tkinter).
No escribe en SQLite. No genera PDF. No toca servidor.py.

Reutiliza las funciones existentes de procesador.py sin modificar ese archivo.
"""
from datetime import datetime, timedelta, time, date
from collections import defaultdict

import pandas as pd

from procesador import (
    cargar_config,
    cargar_feriados,
    cargar_dias_paro,
    cargar_asignaciones_especiales,
    normalizar_depto,
    is_weekend,
    obtener_inicio_asignado,
    obtener_horario_fijo,
    resolver_hora_inicio,
    inferir_inicio_grupal,
    _df_to_registros,
    _agrupar_por_empleado,
    _limpiar_y_emparejar,
    _debe_imputarse_al_dia_anterior,
    EXCLUIR_DE_INFERENCIA,
    LATE_TOLERANCE_MIN,
)

# Estados que cuentan como "día evaluado" en el resumen mensual
_DIAS_EVALUADOS = {"PUNTUAL", "TARDE", "INCOMPLETA"}


# ─── Normalización ────────────────────────────────────────────────────────────

def normalizar_archivo_fichadas(df):
    """
    Normaliza un DataFrame de fichadas.
    Acepta columnas originales del reloj ('Nro. de usuario', etc.)
    o ya normalizadas ('Legajo', 'FechaHora', 'Tipo').
    Devuelve un DataFrame limpio sin modificar el original.
    """
    df = df.copy()

    rename = {
        "Nro. de usuario": "Legajo",
        "Fecha/Hora":      "FechaHora",
        "Tipo de registro": "Tipo",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    for col in ("Legajo", "FechaHora", "Tipo"):
        if col not in df.columns:
            raise ValueError(f"Columna requerida ausente: '{col}'")

    df["FechaHora"] = pd.to_datetime(df["FechaHora"], errors="coerce")
    df = df.dropna(subset=["FechaHora"]).copy()

    df["Legajo"] = df["Legajo"].astype(str).str.strip()

    df["Tipo"] = df["Tipo"].astype(str).str.upper().str.strip()
    df = df[df["Tipo"].isin(["ENTRADA", "SALIDA", "BREAK"])].copy()

    if "Nombre" in df.columns:
        df["Nombre"] = df["Nombre"].astype(str).str.strip()
        df.loc[df["Nombre"].isin(["", "nan", "None"]), "Nombre"] = None
    else:
        df["Nombre"] = None

    if "Departamento" in df.columns:
        df["Departamento"] = df["Departamento"].astype(str).apply(normalizar_depto)
        df.loc[df["Departamento"].isin(["", "nan", "none"]), "Departamento"] = None
    else:
        df["Departamento"] = None

    # Forward-fill Nombre y Departamento dentro de cada legajo
    df = df.sort_values(["Legajo", "FechaHora"], kind="mergesort")
    df["Nombre"] = (
        df.groupby("Legajo")["Nombre"].transform(lambda s: s.ffill().bfill())
    )
    df["Departamento"] = (
        df.groupby("Legajo")["Departamento"].transform(lambda s: s.ffill().bfill())
    )
    df["Nombre"] = df["Nombre"].fillna(df["Legajo"])
    df["Departamento"] = df["Departamento"].fillna("")

    df = df.drop_duplicates(subset=["Legajo", "FechaHora", "Tipo"]).copy()

    df = df.sort_values(
        ["Departamento", "Legajo", "FechaHora"], kind="mergesort"
    ).reset_index(drop=True)

    return df


# ─── Filtro de período ────────────────────────────────────────────────────────

def filtrar_periodo(df, fecha_desde, fecha_hasta):
    """
    Filtra el DataFrame al rango [fecha_desde, fecha_hasta] inclusive.
    Acepta date, datetime o str 'YYYY-MM-DD'.
    Lanza ValueError si las fechas son inválidas o están invertidas.
    """
    def _parse(d):
        if isinstance(d, datetime):
            return d.date()
        if isinstance(d, date):
            return d
        if isinstance(d, str):
            return datetime.strptime(d, "%Y-%m-%d").date()
        raise ValueError(f"Fecha inválida: {d!r}")

    fd = _parse(fecha_desde)
    fh = _parse(fecha_hasta)
    if fd > fh:
        raise ValueError(f"fecha_desde ({fd}) debe ser <= fecha_hasta ({fh})")

    if "FechaHora" not in df.columns:
        raise ValueError("El DataFrame no tiene columna 'FechaHora'")

    col = pd.to_datetime(df["FechaHora"], errors="coerce")
    mask = (col.dt.date >= fd) & (col.dt.date <= fh)
    return df[mask].copy()


# ─── Motor principal ──────────────────────────────────────────────────────────

def calcular_jornadas_puntualidad(
    df,
    feriados=None,
    excluir_tardanza=None,
    archivo_origen="",
):
    """
    Calcula jornadas de puntualidad a partir de un DataFrame de fichadas.
    Devuelve lista de dicts (una entrada por empleado/fecha con registros).
    No modifica el DataFrame original. No escribe en SQLite.
    """
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    df_norm = normalizar_archivo_fichadas(df)

    config = cargar_config()
    if feriados is None:
        feriados = cargar_feriados(config)
    excluir_tardanza = {str(x).strip() for x in (excluir_tardanza or set())}
    dias_paro = cargar_dias_paro(config)
    asignaciones = cargar_asignaciones_especiales()

    registros = _df_to_registros(df_norm)
    grupos = _agrupar_por_empleado(registros)

    inicio_grupal = inferir_inicio_grupal(
        registros,
        asignaciones=asignaciones,
        feriados=feriados,
        dias_paro=dias_paro,
        excluir_legajos=EXCLUIR_DE_INFERENCIA,
    )

    jornadas = []

    for (depto, legajo, nombre), eventos in grupos.items():
        legajo_str = str(legajo)
        es_excluido = legajo_str in excluir_tardanza

        # Timestamps de ENTRADA reales (para distinguir del (dt,dt) de SALIDA-sin-entrada)
        dt_entradas = {ev["dt"] for ev in eventos if ev["tipo"] == "ENTRADA"}

        pares = _limpiar_y_emparejar(eventos)

        # Asignar cada par a su fecha correcta (regla de madrugada)
        por_dia_pares = defaultdict(list)
        for e, s in pares:
            fecha_dest = e.date()
            if _debe_imputarse_al_dia_anterior(
                e=e, s=s, depto=depto, legajo=legajo_str,
                inicio_grupal=inicio_grupal, asignaciones=asignaciones,
                dias_paro=dias_paro, feriados=feriados, config=config,
            ):
                fecha_dest = e.date() - timedelta(days=1)
            por_dia_pares[fecha_dest].append((e, s))

        for fecha in sorted(por_dia_pares.keys()):
            tramos = por_dia_pares[fecha]
            fecha_str = fecha.strftime("%Y-%m-%d")
            es_feriado = fecha in feriados
            es_finsem  = is_weekend(fecha)
            es_paro    = fecha_str in dias_paro

            # Entradas reales del día (excluye los (dt,dt) de SALIDA-sin-entrada)
            entradas_reales = sorted(e for e, s in tramos if e in dt_entradas)
            tiene_entrada_real = bool(entradas_reales)
            # Tramo incompleto = ENTRADA sin SALIDA correspondiente
            tiene_incompleto = any(e == s and e in dt_entradas for e, s in tramos)

            hora_programada = None
            hora_entrada    = None
            minutos_tarde   = 0
            es_tarde        = 0
            observacion     = ""

            # Prioridad de estados especiales (mayor a menor)
            if es_feriado:
                estado      = "FERIADO"
                observacion = "Feriado"
            elif es_finsem:
                estado      = "FIN_DE_SEMANA"
                observacion = "Fin de semana"
            elif es_paro:
                estado      = "PARO"
                observacion = "Día de paro"
            elif es_excluido:
                estado      = "EXCLUIDA"
                observacion = "Legajo excluido del control de tardanza"
            elif not tiene_entrada_real:
                estado      = "SIN_ENTRADA"
                observacion = "Sin entrada válida"
            else:
                primera_entrada = entradas_reales[0]
                hora_entrada    = primera_entrada.strftime("%H:%M")

                inicio_asignado = obtener_inicio_asignado(asignaciones, legajo_str, fecha)
                dyn_start = inicio_asignado if inicio_asignado else resolver_hora_inicio(
                    d=fecha, depto=depto, inicio_grupal=inicio_grupal,
                    config=config, es_paro=False, legajo=legajo_str,
                )
                hora_programada = dyn_start.strftime("%H:%M")

                inicio_dt = datetime.combine(fecha, dyn_start)
                diff_min  = (primera_entrada - inicio_dt).total_seconds() / 60
                minutos_tarde = max(0, int(diff_min))
                es_tarde      = 1 if diff_min >= LATE_TOLERANCE_MIN else 0

                obs_partes = []
                if inicio_asignado:
                    obs_partes.append("Asignación especial")
                elif obtener_horario_fijo(depto, fecha, config):
                    obs_partes.append("Horario fijo")
                elif (depto, fecha, legajo_str) in inicio_grupal:
                    obs_partes.append("Horario inferido por cuadrilla")

                if tiene_incompleto:
                    estado = "INCOMPLETA"
                    obs_partes.append("Fichada incompleta")
                    if es_tarde:
                        obs_partes.append("Llegada tarde")
                elif es_tarde:
                    estado = "TARDE"
                    obs_partes.append("Llegada tarde")
                else:
                    estado = "PUNTUAL"
                    if diff_min > 0:
                        obs_partes.append("Dentro de tolerancia")

                observacion = ". ".join(obs_partes)

            jornadas.append({
                "fecha":          fecha_str,
                "anio":           fecha.year,
                "mes":            fecha.month,
                "departamento":   depto,
                "legajo":         legajo_str,
                "nombre":         nombre,
                "hora_programada": hora_programada,
                "hora_entrada":   hora_entrada,
                "minutos_tarde":  minutos_tarde,
                "es_tarde":       es_tarde,
                "estado_jornada": estado,
                "observacion":    observacion,
                "origen":         "CALCULO_AUTOMATICO",
                "archivo_origen": archivo_origen or "",
                "procesado_en":   ahora,
            })

    return jornadas


# ─── Resúmenes ────────────────────────────────────────────────────────────────

def resumir_por_mes(jornadas):
    """
    Genera un resumen mensual por anio + mes + departamento + legajo.
    No mezcla empleados de distintos departamentos aunque tengan el mismo legajo.
    Días evaluados: solo PUNTUAL, TARDE, INCOMPLETA.
    """
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    acum = defaultdict(lambda: {
        "nombre": "", "dias_evaluados": 0,
        "cantidad_tardanzas": 0, "minutos_tarde": 0,
        "archivo_origen": "", "procesado_en": ahora,
    })

    for j in jornadas:
        clave = (j["anio"], j["mes"], j["departamento"], j["legajo"])
        g = acum[clave]
        g["nombre"]        = j["nombre"]
        g["archivo_origen"] = j.get("archivo_origen", "")

        if j["estado_jornada"] in _DIAS_EVALUADOS:
            g["dias_evaluados"] += 1
        if j.get("es_tarde") == 1:
            g["cantidad_tardanzas"] += 1
            g["minutos_tarde"]      += j.get("minutos_tarde", 0)

    resumenes = []
    for (anio, mes, depto, legajo), g in acum.items():
        resumenes.append({
            "anio":               anio,
            "mes":                mes,
            "departamento":       depto,
            "legajo":             legajo,
            "nombre":             g["nombre"],
            "dias_evaluados":     g["dias_evaluados"],
            "cantidad_tardanzas": g["cantidad_tardanzas"],
            "minutos_tarde":      g["minutos_tarde"],
            "estado_mensual":     obtener_estado_mensual(g["cantidad_tardanzas"]),
            "origen":             "CALCULO_AUTOMATICO",
            "archivo_origen":     g["archivo_origen"],
            "procesado_en":       g["procesado_en"],
        })

    resumenes.sort(key=lambda r: (r["anio"], r["mes"], r["departamento"], r["legajo"]))
    return resumenes


# ─── Clasificadores de estado ─────────────────────────────────────────────────

def obtener_estado_mensual(cantidad_tardanzas):
    """0-2 → VERDE | 3-4 → AMARILLO | 5+ → NARANJA"""
    if cantidad_tardanzas >= 5:
        return "NARANJA"
    if cantidad_tardanzas >= 3:
        return "AMARILLO"
    return "VERDE"


def obtener_estado_anual(cantidad_anual):
    """0-9 → NORMAL | 10-12 → ADVERTENCIA_ANUAL | 13+ → ROJO"""
    if cantidad_anual >= 13:
        return "ROJO"
    if cantidad_anual >= 10:
        return "ADVERTENCIA_ANUAL"
    return "NORMAL"


def obtener_estado_visual(cantidad_mes, cantidad_anual):
    """
    Estado de mayor prioridad visual:
    ROJO > NARANJA > AMARILLO > VERDE
    """
    if cantidad_anual >= 13:
        return "ROJO"
    if cantidad_mes >= 5:
        return "NARANJA"
    if cantidad_anual >= 10 or cantidad_mes >= 3:
        return "AMARILLO"
    return "VERDE"
