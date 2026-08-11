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

Mismo día, la usuaria aclaró una regla de negocio más: para pagar el plus
solo cuentan los meses YA LIQUIDADOS (pagados en el ciclo de sueldos) --
el último cierre recién hecho en el sistema todavía no está liquidado y
no debe sumarse. Se agregó periodos.liquidado_en (marcado manual desde
/periodos/historial, botón "Marcar liquidado") y /plus-vacacional ahora
exige liquidado_en no vacío además de estado ACTIVO.
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


def _crear_periodo(db_file, departamento_guardado, fecha_desde, fecha_hasta,
                    legajo="133", liquidado=True):
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    liquidado_en = f"{fecha_hasta}T12:00:00" if liquidado else ""
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado, saldo_anterior, liquidado_en) VALUES (?,?,?,?,?,?,?,?,?)",
        (f"{fecha_hasta}T12:00:00", 1, 4, f"periodo_{departamento_guardado}.json",
         fecha_desde, fecha_hasta, "ACTIVO", "{}", liquidado_en),
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


def test_plus_vacacional_no_cuenta_cierre_sin_liquidar(db_temporal):
    """Pedido explícito de la usuaria (11/08/2026): el último cierre hecho
    en el sistema todavía no fue pagado en el ciclo de sueldos, así que no
    debe sumarse a Plus Vacacional hasta marcarse liquidado."""
    _crear_periodo(db_temporal, "Redes", "2026-07-01", "2026-07-26", legajo="133", liquidado=False)

    with servidor.app.test_client() as c:
        resp = c.get("/plus-vacacional?depto=redes")
        html = resp.get_data(as_text=True)
        assert "ZABALA ANTONIO" not in html


def test_marcar_liquidado_hace_aparecer_el_cierre_en_plus_vacacional(db_temporal):
    pid = _crear_periodo(db_temporal, "Redes", "2026-07-01", "2026-07-26", liquidado=False)

    with servidor.app.test_client() as c:
        assert "ZABALA ANTONIO" not in c.get("/plus-vacacional?depto=redes").get_data(as_text=True)

        resp = c.post(f"/periodos/marcar-liquidado/{pid}")
        assert resp.status_code == 200
        assert resp.get_json()["liquidado"] is True

        assert "ZABALA ANTONIO" in c.get("/plus-vacacional?depto=redes").get_data(as_text=True)

        # Se puede deshacer.
        resp2 = c.post(f"/periodos/marcar-liquidado/{pid}", data={"quitar": "1"})
        assert resp2.get_json()["liquidado"] is False
        assert "ZABALA ANTONIO" not in c.get("/plus-vacacional?depto=redes").get_data(as_text=True)
