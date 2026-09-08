# -*- coding: utf-8 -*-
"""
Plus Vacacional etiquetaba cada columna por periodos.fecha_desde (inicio de
la ventana de datos), no por cerrado_en (cuándo se cerró de verdad) --
mismo patrón ya documentado y arreglado en
tests/test_informe_mensual_filtra_por_cierre_no_por_datos.py, pero en un
lugar distinto del código (plus_vacacional() nunca se tocó en ese fix).

Un cierre "de julio" recerrado tarde puede tener fecha_desde de fines de
junio (la semana que cruza el límite de mes) -- eso hacía que su columna
se etiquetara "Junio 2026", duplicando la del cierre real de junio, en vez
de "Julio 2026" (reportado por la usuaria el 08/09/2026 viendo dos
columnas "JUN 2026" seguidas en la pantalla).
"""
import sqlite3

import pytest

import servidor


@pytest.fixture
def db_temporal(tmp_path, monkeypatch):
    db_file = tmp_path / "cierres_test.db"
    monkeypatch.setattr(servidor, "DATOS_DIR", tmp_path)
    monkeypatch.setattr(servidor, "DB_FILE", db_file)
    servidor._init_db()
    return db_file


@pytest.fixture(autouse=True)
def _patch_io(monkeypatch):
    monkeypatch.setattr(servidor, "_autenticado", lambda: True)


@pytest.fixture
def client():
    servidor.app.config["TESTING"] = True
    with servidor.app.test_client() as c:
        yield c


def _conn(db_file):
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    return conn


def _crear_periodo_liquidado(db_file, fecha_desde, fecha_hasta, cerrado_en, legajo="133"):
    conn = _conn(db_file)
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado, liquidado_en) VALUES (?,?,?,?,?,?,?,?)",
        (cerrado_en, 1, 4, "periodo_test.json", fecha_desde, fecha_hasta,
         "ACTIVO", cerrado_en),
    )
    pid = cur.lastrowid
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
        "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, legajo, "ZABALA ANTONIO", "Redes", "3h", "0h", 0, 0, 0, "[]", 1),
    )
    conn.commit()
    conn.close()
    return pid


def test_label_mes_por_rango_usa_mayoria_de_dias():
    # 2 días en junio, 26 en julio -> julio
    assert servidor._label_mes_por_rango("2026-06-29", "2026-07-26") == "Jul 2026"
    # Mayoría clara dentro de un solo mes
    assert servidor._label_mes_por_rango("2026-06-01", "2026-06-28") == "Jun 2026"
    # 27 días en julio, 3 en agosto -> julio
    assert servidor._label_mes_por_rango("2026-07-05", "2026-08-03") == "Jul 2026"


def test_columna_de_cierre_recerrado_tarde_etiqueta_por_mes_de_cierre(db_temporal, client):
    _crear_periodo_liquidado(db_temporal, "2026-05-01", "2026-05-28", "2026-05-30T10:00:00")
    _crear_periodo_liquidado(db_temporal, "2026-06-01", "2026-06-28", "2026-06-29T10:00:00")
    # "Julio": datos desde fin de junio, cerrado (y liquidado) recién en julio.
    _crear_periodo_liquidado(db_temporal, "2026-06-29", "2026-07-26", "2026-07-20T15:18:04")

    resp = client.get("/plus-vacacional?depto=redes")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)

    assert texto.count("Jun 2026") == 1, "no debe duplicarse la columna de junio"
    assert "Jul 2026" in texto, "el tercer cierre debe etiquetarse por el mes con más días del rango (julio), no por fecha_desde a secas (junio)"
