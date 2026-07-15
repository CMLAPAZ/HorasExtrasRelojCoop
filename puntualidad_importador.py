# -*- coding: utf-8 -*-
"""
puntualidad_importador.py - Importador historico para Control de Puntualidad.

Modulo nuevo y aislado. Lee archivos de fichadas, delega el calculo en
puntualidad_service.py y persiste exclusivamente en datos/puntualidad.db.
No modifica el sistema actual.
"""
import os
from datetime import date, datetime

import pandas as pd

from puntualidad_db import (
    guardar_jornadas,
    guardar_resumenes_mensuales,
    inicializar_base_puntualidad,
    registrar_importacion,
)
from puntualidad_service import (
    calcular_jornadas_puntualidad,
    filtrar_periodo,
    normalizar_archivo_fichadas,
    resumir_por_mes,
)


EXTENSIONES_FICHADAS = (".xlsx", ".xls", ".csv")


def leer_archivo_fichadas(ruta_archivo):
    """
    Lee un archivo de fichadas Excel/CSV y devuelve un DataFrame.
    Acepta CSV separado por ; o ,.
    """
    ruta = str(ruta_archivo)
    if not os.path.exists(ruta):
        raise FileNotFoundError(f"No existe el archivo: {ruta}")

    lower = ruta.lower()
    if lower.endswith(".csv"):
        try:
            df = pd.read_csv(ruta, encoding="utf-8", sep=";")
            if df.shape[1] < 3:
                df = pd.read_csv(ruta, encoding="utf-8", sep=",")
        except Exception:
            df = pd.read_csv(ruta, encoding="utf-8", sep=",")
    elif lower.endswith((".xlsx", ".xls")):
        df = pd.read_excel(ruta)
    else:
        raise ValueError(f"Extension no soportada: {os.path.basename(ruta)}")

    return df


def _parse_fecha(valor, nombre):
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        try:
            return datetime.strptime(valor.strip(), "%Y-%m-%d").date()
        except Exception as exc:
            raise ValueError(f"{nombre} debe tener formato YYYY-MM-DD.") from exc
    raise ValueError(f"{nombre} invalida: {valor!r}")


def detectar_periodo(df):
    """Devuelve (fecha_min, fecha_max) del DataFrame de fichadas."""
    df_norm = normalizar_archivo_fichadas(df)
    if df_norm.empty:
        raise ValueError("El archivo no tiene fichadas validas.")
    fechas = pd.to_datetime(df_norm["FechaHora"], errors="coerce").dropna()
    if fechas.empty:
        raise ValueError("El archivo no tiene fechas validas.")
    return fechas.min().date(), fechas.max().date()


def _meses_de(resumenes):
    return sorted({(int(r["anio"]), int(r["mes"])) for r in resumenes})


def _meses_texto(meses):
    return ", ".join(f"{anio}-{mes:02d}" for anio, mes in meses)


def importar_archivo_puntualidad(
    base_dir,
    ruta_archivo,
    fecha_desde=None,
    fecha_hasta=None,
    reemplazar_mes=False,
    excluir_tardanza=None,
):
    """
    Importa un archivo a datos/puntualidad.db.

    reemplazar_mes=False: los duplicados se omiten por UNIQUE.
    reemplazar_mes=True: borra y recalcula completos los meses presentes.
    """
    inicializar_base_puntualidad(base_dir)

    df = leer_archivo_fichadas(ruta_archivo)
    df_norm = normalizar_archivo_fichadas(df)
    periodo_min, periodo_max = detectar_periodo(df_norm)

    desde = _parse_fecha(fecha_desde, "fecha_desde") or periodo_min
    hasta = _parse_fecha(fecha_hasta, "fecha_hasta") or periodo_max
    if desde > hasta:
        raise ValueError(f"fecha_desde ({desde}) debe ser <= fecha_hasta ({hasta})")

    df_periodo = filtrar_periodo(df_norm, desde, hasta)
    if df_periodo.empty:
        raise ValueError("No hay fichadas dentro del periodo solicitado.")

    archivo_origen = os.path.basename(str(ruta_archivo))
    jornadas = calcular_jornadas_puntualidad(
        df_periodo,
        excluir_tardanza=excluir_tardanza,
        archivo_origen=archivo_origen,
    )
    if not jornadas:
        raise ValueError("No se generaron jornadas de puntualidad.")

    resumenes = resumir_por_mes(jornadas)
    meses = _meses_de(resumenes)

    jornadas_guardadas = guardar_jornadas(
        base_dir,
        jornadas,
        reemplazar_mes=reemplazar_mes,
    )
    resumenes_guardados = guardar_resumenes_mensuales(
        base_dir,
        resumenes,
        reemplazar_mes=reemplazar_mes,
    )

    duplicados_omitidos = 0
    if not reemplazar_mes:
        duplicados_omitidos = max(0, len(jornadas) - int(jornadas_guardadas))

    importacion_id = registrar_importacion(base_dir, {
        "archivo_origen": archivo_origen,
        "periodo_desde": desde.strftime("%Y-%m-%d"),
        "periodo_hasta": hasta.strftime("%Y-%m-%d"),
        "registros_leidos": len(df_periodo),
        "duplicados_omitidos": duplicados_omitidos,
        "meses_procesados": _meses_texto(meses),
        "observacion": "Importacion historica de puntualidad",
    })

    return {
        "importacion_id": importacion_id,
        "archivo_origen": archivo_origen,
        "periodo_desde": desde.strftime("%Y-%m-%d"),
        "periodo_hasta": hasta.strftime("%Y-%m-%d"),
        "registros_leidos": len(df_periodo),
        "jornadas_calculadas": len(jornadas),
        "jornadas_guardadas": int(jornadas_guardadas),
        "resumenes_calculados": len(resumenes),
        "resumenes_guardados": int(resumenes_guardados),
        "duplicados_omitidos": duplicados_omitidos,
        "meses_procesados": _meses_texto(meses),
        "reemplazar_mes": bool(reemplazar_mes),
    }


def importar_carpeta_puntualidad(
    base_dir,
    carpeta,
    reemplazar_mes=False,
    continuar_con_errores=False,
    excluir_tardanza=None,
):
    """
    Importa todos los archivos soportados de una carpeta, ordenados por nombre.
    Retorna {"importados": [...], "errores": [...]}.
    """
    if not os.path.isdir(carpeta):
        raise NotADirectoryError(f"No existe la carpeta: {carpeta}")

    archivos = sorted(
        os.path.join(carpeta, nombre)
        for nombre in os.listdir(carpeta)
        if nombre.lower().endswith(EXTENSIONES_FICHADAS)
    )

    resultado = {"importados": [], "errores": []}
    for ruta in archivos:
        try:
            resultado["importados"].append(importar_archivo_puntualidad(
                base_dir,
                ruta,
                reemplazar_mes=reemplazar_mes,
                excluir_tardanza=excluir_tardanza,
            ))
        except Exception as exc:
            error = {"archivo": os.path.basename(ruta), "error": str(exc)}
            resultado["errores"].append(error)
            if not continuar_con_errores:
                raise

    return resultado
