# -*- coding: utf-8 -*-
"""
puntualidad_db.py — Persistencia SQLite para Control de Puntualidad.
Base de datos local, independiente de cierres.db.
"""
import sqlite3
import os
from datetime import datetime


def obtener_ruta_db(base_dir):
    """Ruta absoluta a puntualidad.db dentro de base_dir/datos/."""
    return os.path.join(base_dir, "datos", "puntualidad.db")


def _conectar(base_dir):
    conn = sqlite3.connect(obtener_ruta_db(base_dir))
    conn.row_factory = sqlite3.Row
    return conn


def _ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ─── Inicialización ───────────────────────────────────────────────────────────

def inicializar_base_puntualidad(base_dir):
    """Crea datos/ y todas las tablas si no existen. Idempotente."""
    os.makedirs(os.path.join(base_dir, "datos"), exist_ok=True)
    conn = _conectar(base_dir)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS puntualidad_jornada (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha            TEXT    NOT NULL,
                anio             INTEGER NOT NULL,
                mes              INTEGER NOT NULL,
                departamento     TEXT    NOT NULL,
                legajo           TEXT    NOT NULL,
                nombre           TEXT    NOT NULL,
                hora_programada  TEXT,
                hora_entrada     TEXT,
                minutos_tarde    INTEGER NOT NULL DEFAULT 0,
                es_tarde         INTEGER NOT NULL DEFAULT 0,
                estado_jornada   TEXT    NOT NULL,
                observacion      TEXT,
                origen           TEXT    NOT NULL,
                archivo_origen   TEXT,
                procesado_en     TEXT    NOT NULL,
                UNIQUE(anio, mes, legajo, fecha)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS puntualidad_mes (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                anio                INTEGER NOT NULL,
                mes                 INTEGER NOT NULL,
                departamento        TEXT    NOT NULL,
                legajo              TEXT    NOT NULL,
                nombre              TEXT    NOT NULL,
                dias_evaluados      INTEGER NOT NULL DEFAULT 0,
                cantidad_tardanzas  INTEGER NOT NULL DEFAULT 0,
                minutos_tarde       INTEGER NOT NULL DEFAULT 0,
                estado_mensual      TEXT    NOT NULL,
                origen              TEXT    NOT NULL,
                archivo_origen      TEXT,
                procesado_en        TEXT    NOT NULL,
                UNIQUE(anio, mes, legajo)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS puntualidad_importacion (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                archivo_origen      TEXT,
                periodo_desde       TEXT,
                periodo_hasta       TEXT,
                registros_leidos    INTEGER NOT NULL DEFAULT 0,
                duplicados_omitidos INTEGER NOT NULL DEFAULT 0,
                meses_procesados    TEXT,
                observacion         TEXT,
                procesado_en        TEXT    NOT NULL
            )
        """)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─── Escritura ────────────────────────────────────────────────────────────────

def guardar_jornadas(base_dir, jornadas, reemplazar_mes=False):
    """
    Inserta jornadas en puntualidad_jornada.
    reemplazar_mes=True: elimina primero todos los registros del mismo anio/mes.
    reemplazar_mes=False: omite silenciosamente los duplicados (UNIQUE constraint).
    """
    if not jornadas:
        return 0

    conn = _conectar(base_dir)
    try:
        if reemplazar_mes:
            for anio, mes in {(j["anio"], j["mes"]) for j in jornadas}:
                conn.execute(
                    "DELETE FROM puntualidad_jornada WHERE anio=? AND mes=?",
                    (anio, mes)
                )

        conn.executemany(
            """
            INSERT OR IGNORE INTO puntualidad_jornada
                (fecha, anio, mes, departamento, legajo, nombre,
                 hora_programada, hora_entrada, minutos_tarde, es_tarde,
                 estado_jornada, observacion, origen, archivo_origen, procesado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    j["fecha"], j["anio"], j["mes"], j["departamento"], j["legajo"],
                    j["nombre"], j.get("hora_programada"), j.get("hora_entrada"),
                    j.get("minutos_tarde", 0), j.get("es_tarde", 0),
                    j["estado_jornada"], j.get("observacion"),
                    j["origen"], j.get("archivo_origen"),
                    j.get("procesado_en") or _ahora(),
                )
                for j in jornadas
            ],
        )
        conn.commit()
        return conn.total_changes
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"Error al guardar jornadas: {e}") from e
    finally:
        conn.close()


def guardar_resumenes_mensuales(base_dir, resumenes, reemplazar_mes=False):
    """
    Inserta resúmenes en puntualidad_mes.
    reemplazar_mes=True: elimina primero todos los registros del mismo anio/mes.
    reemplazar_mes=False: omite silenciosamente los duplicados (UNIQUE constraint).
    """
    if not resumenes:
        return 0

    conn = _conectar(base_dir)
    try:
        if reemplazar_mes:
            for anio, mes in {(r["anio"], r["mes"]) for r in resumenes}:
                conn.execute(
                    "DELETE FROM puntualidad_mes WHERE anio=? AND mes=?",
                    (anio, mes)
                )

        conn.executemany(
            """
            INSERT OR IGNORE INTO puntualidad_mes
                (anio, mes, departamento, legajo, nombre,
                 dias_evaluados, cantidad_tardanzas, minutos_tarde,
                 estado_mensual, origen, archivo_origen, procesado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["anio"], r["mes"], r["departamento"], r["legajo"], r["nombre"],
                    r.get("dias_evaluados", 0), r.get("cantidad_tardanzas", 0),
                    r.get("minutos_tarde", 0), r["estado_mensual"],
                    r["origen"], r.get("archivo_origen"),
                    r.get("procesado_en") or _ahora(),
                )
                for r in resumenes
            ],
        )
        conn.commit()
        return conn.total_changes
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"Error al guardar resúmenes mensuales: {e}") from e
    finally:
        conn.close()


def registrar_importacion(base_dir, datos_importacion):
    """Registra una importación. Retorna el id del registro creado."""
    conn = _conectar(base_dir)
    try:
        cur = conn.execute(
            """
            INSERT INTO puntualidad_importacion
                (archivo_origen, periodo_desde, periodo_hasta,
                 registros_leidos, duplicados_omitidos,
                 meses_procesados, observacion, procesado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datos_importacion.get("archivo_origen"),
                datos_importacion.get("periodo_desde"),
                datos_importacion.get("periodo_hasta"),
                datos_importacion.get("registros_leidos", 0),
                datos_importacion.get("duplicados_omitidos", 0),
                datos_importacion.get("meses_procesados"),
                datos_importacion.get("observacion"),
                datos_importacion.get("procesado_en") or _ahora(),
            ),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"Error al registrar importación: {e}") from e
    finally:
        conn.close()


# ─── Consultas ────────────────────────────────────────────────────────────────

def consultar_jornadas_mes(base_dir, anio, mes, departamento=None, legajo=None):
    """Retorna lista de dicts con jornadas del mes, filtrable por depto y legajo."""
    conn = _conectar(base_dir)
    try:
        sql = "SELECT * FROM puntualidad_jornada WHERE anio=? AND mes=?"
        params = [anio, mes]
        if departamento:
            sql += " AND departamento=?"
            params.append(departamento)
        if legajo is not None:
            sql += " AND legajo=?"
            params.append(str(legajo))
        sql += " ORDER BY departamento, legajo, fecha"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def consultar_resumen_mes(base_dir, anio, mes, departamento=None):
    """Retorna lista de dicts con resúmenes del mes, filtrable por depto."""
    conn = _conectar(base_dir)
    try:
        sql = "SELECT * FROM puntualidad_mes WHERE anio=? AND mes=?"
        params = [anio, mes]
        if departamento:
            sql += " AND departamento=?"
            params.append(departamento)
        sql += " ORDER BY departamento, legajo"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def consultar_acumulado_anual(base_dir, anio, departamento=None):
    """
    Calcula el acumulado anual sumando puntualidad_mes.
    No usa tabla separada — el total se computa en tiempo de consulta.
    Retorna lista de dicts ordenada por departamento y legajo.
    """
    conn = _conectar(base_dir)
    try:
        sql = """
            SELECT legajo, nombre, departamento,
                   SUM(dias_evaluados)     AS dias_evaluados,
                   SUM(cantidad_tardanzas) AS cantidad_tardanzas,
                   SUM(minutos_tarde)      AS minutos_tarde
            FROM puntualidad_mes
            WHERE anio=?
        """
        params = [anio]
        if departamento:
            sql += " AND departamento=?"
            params.append(departamento)
        sql += " GROUP BY legajo, nombre, departamento ORDER BY departamento, legajo"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ─── Utilidades de control ────────────────────────────────────────────────────

def mes_ya_procesado(base_dir, anio, mes):
    """True si ya existe al menos un registro en puntualidad_mes para ese anio/mes."""
    conn = _conectar(base_dir)
    try:
        r = conn.execute(
            "SELECT 1 FROM puntualidad_mes WHERE anio=? AND mes=? LIMIT 1",
            (anio, mes),
        ).fetchone()
        return r is not None
    finally:
        conn.close()


def eliminar_mes(base_dir, anio, mes):
    """
    Elimina todos los registros de jornadas y resúmenes del mes indicado.
    Retorna dict con cantidad de filas eliminadas por tabla.
    """
    conn = _conectar(base_dir)
    try:
        rj = conn.execute(
            "DELETE FROM puntualidad_jornada WHERE anio=? AND mes=?", (anio, mes)
        )
        rm = conn.execute(
            "DELETE FROM puntualidad_mes WHERE anio=? AND mes=?", (anio, mes)
        )
        conn.commit()
        return {"jornadas": rj.rowcount, "resumenes": rm.rowcount}
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"Error al eliminar mes {anio}/{mes}: {e}") from e
    finally:
        conn.close()
