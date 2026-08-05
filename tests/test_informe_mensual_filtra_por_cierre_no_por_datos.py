# -*- coding: utf-8 -*-
"""
Los informes mensuales combinados (/periodos/informe_mensual y
/periodos/informe_mensual_francos, botones de la pantalla "Cierres")
filtraban por periodos.fecha_desde (inicio de la ventana de datos) para
decidir a qué mes pertenece un cierre. Un cierre recerrado tarde (ver
incidente Administración, sesión 03/08/2026: datos de junio, cerrado_en
julio) tiene fecha_desde de un mes distinto al mes en que se cerró de
verdad -- así que al elegir "julio" en el selector, ese cierre no
aparecía, aunque el usuario esperaba verlo ahí (05/08/2026: "en este
boton verde no parecen los saldos de redes ni administracion").

Fix: ambas rutas ahora filtran por cerrado_en (la fecha/hora real de
cierre), no por fecha_desde.
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


def _conn(db_file):
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    return conn


def _crear_periodo_recerrado_tarde(db_file):
    """Datos de junio (fecha_desde/fecha_hasta), cerrado recién en julio."""
    conn = _conn(db_file)
    cerrado_en = "2026-07-03T15:18:04.000000"
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado, saldo_anterior) VALUES (?,?,?,?,?,?,?,?)",
        (cerrado_en, 1, 4, "periodo_test.json", "2026-06-01", "2026-06-28", "ACTIVO", "{}"),
    )
    pid = cur.lastrowid
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
        "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, "133", "ZABALA ANTONIO", "Redes", "3h", "0h", 0, 1, 0, "[]", 1),
    )
    conn.commit()
    conn.close()
    return pid


def test_informe_mensual_francos_incluye_cierre_recerrado_tarde_en_mes_de_cierre(db_temporal):
    _crear_periodo_recerrado_tarde(db_temporal)

    # El mes de los DATOS (junio) ya no debe ser el criterio.
    pdf_junio = servidor._generar_pdf_informe_mensual_francos("2026-06")
    assert pdf_junio is None, "no debería aparecer en junio -- ahí no se cerró"

    # El mes en que se cerró de verdad (julio) sí debe traerlo.
    pdf_julio = servidor._generar_pdf_informe_mensual_francos("2026-07")
    assert pdf_julio is not None, "debería aparecer en julio -- ahí se cerró de verdad"


def test_informe_mensual_combinado_incluye_cierre_recerrado_tarde_en_mes_de_cierre(db_temporal, monkeypatch):
    servidor.app.config["TESTING"] = True
    monkeypatch.setattr(servidor, "_autenticado", lambda: True)
    _crear_periodo_recerrado_tarde(db_temporal)

    with servidor.app.test_client() as c:
        resp_junio = c.get("/periodos/informe_mensual?mes=2026-06")
        assert resp_junio.status_code == 404, "no debería haber cierres activos en junio"

        resp_julio = c.get("/periodos/informe_mensual?mes=2026-07")
        assert resp_julio.status_code == 200, resp_julio.get_data(as_text=True)
