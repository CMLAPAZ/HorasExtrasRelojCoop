# -*- coding: utf-8 -*-
"""
/plus-vacacional filtraba periodo_empleados.departamento por igualdad
exacta de string ("Redes"). El valor guardado en periodo_cerrar viene tal
cual del resumen armado en ese momento -- puede quedar "redes", "REDES",
etc. según cómo haya llegado el dato -- así que un cierre real, ACTIVO y
visible en /periodos/historial podía no aparecer nunca en Plus Vacacional
(reportado por la usuaria: "el plus de julio no se agrego", Redes y
Administración, 11/08/2026).

Fix: se normaliza con _normalizar_departamento_web() en Python, mismo
criterio que _legajos_actuales_del_depto().
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
    servidor.app.config["TESTING"] = True
    monkeypatch.setattr(servidor, "_autenticado", lambda: True)
    return db_file


def _crear_periodo(db_file, departamento_guardado, fecha_desde, fecha_hasta, legajo="133"):
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado, saldo_anterior) VALUES (?,?,?,?,?,?,?,?)",
        (f"{fecha_hasta}T12:00:00", 1, 4, f"periodo_{departamento_guardado}.json",
         fecha_desde, fecha_hasta, "ACTIVO", "{}"),
    )
    pid = cur.lastrowid
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
        "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, legajo, "ZABALA ANTONIO", departamento_guardado, "3h", "0h", 0, 1, 0, "[]", 1),
    )
    conn.commit()
    conn.close()
    return pid


def test_plus_vacacional_incluye_cierre_con_departamento_en_minuscula(db_temporal):
    """Caso real reportado: el cierre de julio quedó con 'redes' en vez de
    'Redes' en periodo_empleados -- antes desaparecía del todo de la
    pantalla, aunque el cierre estuviera ACTIVO y visible en el historial."""
    _crear_periodo(db_temporal, "redes", "2026-07-01", "2026-07-26")

    with servidor.app.test_client() as c:
        resp = c.get("/plus-vacacional?depto=redes")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "ZABALA ANTONIO" in html


def test_plus_vacacional_incluye_cierre_con_administracion_sin_tilde(db_temporal):
    _crear_periodo(db_temporal, "ADMINISTRACION", "2026-07-01", "2026-07-26", legajo="200")

    with servidor.app.test_client() as c:
        resp = c.get("/plus-vacacional?depto=administracion")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "ZABALA ANTONIO" in html


def test_plus_vacacional_no_mezcla_redes_y_administracion(db_temporal):
    _crear_periodo(db_temporal, "Redes", "2026-07-01", "2026-07-26", legajo="133")
    _crear_periodo(db_temporal, "Administración", "2026-07-01", "2026-07-26", legajo="200")

    with servidor.app.test_client() as c:
        resp = c.get("/plus-vacacional?depto=redes")
        html = resp.get_data(as_text=True)
        assert "133" in html
        # No debe traer el legajo de Administración a la vista de Redes.
        assert ">200<" not in html
