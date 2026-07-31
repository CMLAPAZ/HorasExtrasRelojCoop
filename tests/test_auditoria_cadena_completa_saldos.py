# -*- coding: utf-8 -*-
"""
Auditoría y corrección de cadena completa de saldos de francos
(_recalcular_cadena_completa_legajo, /admin/auditoria-completa-saldos-francos,
/admin/corregir-cadena-completa-saldos-francos).

Reproduce el bug real encontrado en producción: un cierre intermedio deja
un `saldo_anterior` grabado en el cierre siguiente que NO coincide con lo
que _delta_francos_cierre recalcula para el cierre anterior -- y esa
rotura se arrastra hasta el saldo actual en vivo. La auditoría debe
detectar ESO (comparando contra el saldo en vivo de hoy, no solo pares
consecutivos), y la corrección debe arreglar solo el legajo afectado, sin
tocar cierres, periodo_empleados ni al legajo sano.
"""
import json
import sqlite3

import pytest

import servidor


@pytest.fixture
def db_temporal(tmp_path, monkeypatch):
    db_file = tmp_path / "cierres_test.db"
    monkeypatch.setattr(servidor, "DATOS_DIR", tmp_path)
    monkeypatch.setattr(servidor, "DB_FILE", db_file)
    servidor._init_db()
    servidor._sesion.clear()
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


def _crear_cierre(conn, cerrado_en, saldo_anterior, empleados):
    """empleados = [(legajo, nombre, departamento, francos_periodo, tomados_periodo)]"""
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado, saldo_anterior) VALUES (?,?,?,?,?,?,?,?)",
        (cerrado_en, 1, 1, "test.json", "2026-01-01", "2026-01-07", "ACTIVO",
         json.dumps(saldo_anterior)),
    )
    pid = cur.lastrowid
    for leg, nombre, depto, francos, tomados in empleados:
        conn.execute(
            "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
            "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, leg, nombre, depto, "0h", "0h", 0, francos, 0, "[]", 0),
        )
        if tomados:
            conn.execute(
                "INSERT INTO francos_cierre_detalle (periodo_id, legajo, dias, estado, "
                "fecha_desde, fecha_hasta) VALUES (?,?,?,?,?,?)",
                (pid, leg, tomados, "Cerrado", "2026-01-02", "2026-01-02"),
            )
    conn.commit()
    return pid


def _set_saldo_inicial(conn, legajo, nombre, saldo, gen_extra_al_corte=0):
    conn.execute(
        "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, nota, cargado_en, "
        "tomados_al_corte, gen_extra_al_corte, fecha_corte) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(legajo) DO UPDATE SET saldo=excluded.saldo, "
        "gen_extra_al_corte=excluded.gen_extra_al_corte",
        (legajo, nombre, saldo, "setup test", "2026-01-01 00:00:00", 0, gen_extra_al_corte,
         "2026-01-01"),
    )
    conn.commit()


def test_auditoria_detecta_solo_el_legajo_con_cadena_rota(db_temporal):
    conn = _conn(db_temporal)

    # Legajo "10": cadena sana -- cierre 1 (saldo_anterior=5, genera 3) ->
    # debería dejar 8 en el cierre 2, y el 2 lo declara bien (8).
    _crear_cierre(conn, "2026-06-01 10:00:00", {"10": {"saldo": 5, "gen_extra_al_corte": 0}},
                  [("10", "Empleado Sano", "redes", 3, 0)])
    _crear_cierre(conn, "2026-07-01 10:00:00", {"10": {"saldo": 8, "gen_extra_al_corte": 0}},
                  [("10", "Empleado Sano", "redes", 2, 0)])
    # Cierre 2 generó 2 mas -> saldo en vivo correcto = 8 + 2 = 10
    _set_saldo_inicial(conn, "10", "Empleado Sano", 10)

    # Legajo "20": el cierre 1 genera 3 (saldo_anterior=5 -> debería dejar 8),
    # pero el cierre 2 declara (a mano, simulando el bug real) que el
    # saldo_anterior fue 12 en vez de 8 -- una rotura de +4. Esa rotura se
    # arrastra al saldo en vivo actual.
    _crear_cierre(conn, "2026-06-01 10:00:00", {"20": {"saldo": 5, "gen_extra_al_corte": 0}},
                  [("20", "Empleado Roto", "redes", 3, 0)])
    _crear_cierre(conn, "2026-07-01 10:00:00", {"20": {"saldo": 12, "gen_extra_al_corte": 0}},
                  [("20", "Empleado Roto", "redes", 2, 0)])
    # Cierre 2 generó 2 sobre el baseline roto (12) -> saldo en vivo hoy = 14
    _set_saldo_inicial(conn, "20", "Empleado Roto", 14)
    conn.close()

    conn = _conn(db_temporal)
    resultados, con_diferencia, no_aplicables = servidor._auditoria_completa_saldos_francos(conn)
    conn.close()

    por_legajo = {r["legajo"]: r for r in resultados}
    assert por_legajo["10"]["diferencia"] == 0
    assert por_legajo["20"]["saldo_recalculado_completo"] == 10   # 5+3 (c1) +2 (c2) = 10
    assert por_legajo["20"]["diferencia"] == 4                    # 14 declarado - 10 recalculado

    legajos_con_diferencia = {r["legajo"] for r in con_diferencia}
    assert legajos_con_diferencia == {"20"}
    assert no_aplicables == []


def test_legajo_de_depto_sin_fichadas_no_se_toca(db_temporal):
    """Reproduce el bug real: un legajo (ej. 100-Mancioni) tiene un cierre
    viejo de 'periodos' de una época anterior (cuando todavía se procesaba
    por fichadas), pero HOY pertenece a un departamento sin fichadas
    (Ingenieros/Guardias/Internet/Telefonía, tabla empleados_extra) y su
    saldo se gestiona por cierre manual. La auditoría no debe recalcularlo
    ni la corrección debe tocarlo, aunque su viejo cierre de periodos no
    coincida con el saldo actual."""
    conn = _conn(db_temporal)
    _crear_cierre(conn, "2026-06-01 10:00:00", {"100": {"saldo": 0, "gen_extra_al_corte": 0}},
                  [("100", "Mancioni Martin", "redes", 4, 0)])
    # Saldo actual real, fijado DESPUES por el cierre manual de Ingenieros
    # (no coincide con lo que daría el cierre viejo de Redes: 0+4=4).
    conn.execute(
        "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, nota, cargado_en, "
        "tomados_al_corte, gen_extra_al_corte, fecha_corte) VALUES (?,?,?,?,?,?,?,?)",
        ("100", "Mancioni Martin", 5, "Cierre manual francos Ingenieros al 2026-07-08",
         "2026-07-22 12:50:05", 1, 1, "2026-07-08"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO empleados_extra (legajo, nombre, departamento, activo) VALUES (?,?,?,1)",
        ("100", "Mancioni Martin", "Ingenieros"),
    )
    conn.commit()
    conn.close()

    conn = _conn(db_temporal)
    resultados, con_diferencia, no_aplicables = servidor._auditoria_completa_saldos_francos(conn)
    conn.close()

    assert not any(r["legajo"] == "100" for r in resultados)
    assert not any(r["legajo"] == "100" for r in con_diferencia)
    assert any(r["legajo"] == "100" for r in no_aplicables)


def test_correccion_no_toca_legajo_de_depto_sin_fichadas(db_temporal, client):
    conn = _conn(db_temporal)
    _crear_cierre(conn, "2026-06-01 10:00:00", {"100": {"saldo": 0, "gen_extra_al_corte": 0}},
                  [("100", "Mancioni Martin", "redes", 4, 0)])
    conn.execute(
        "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, nota, cargado_en, "
        "tomados_al_corte, gen_extra_al_corte, fecha_corte) VALUES (?,?,?,?,?,?,?,?)",
        ("100", "Mancioni Martin", 5, "Cierre manual francos Ingenieros al 2026-07-08",
         "2026-07-22 12:50:05", 1, 1, "2026-07-08"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO empleados_extra (legajo, nombre, departamento, activo) VALUES (?,?,?,1)",
        ("100", "Mancioni Martin", "Ingenieros"),
    )
    conn.commit()
    conn.close()

    resp = client.get("/admin/corregir-cadena-completa-saldos-francos?confirmar=si")
    data = resp.get_json()
    assert data["total_no_aplicables"] == 1

    conn = _conn(db_temporal)
    saldo = conn.execute(
        "SELECT saldo FROM francos_saldo_inicial WHERE legajo='100'"
    ).fetchone()["saldo"]
    conn.close()
    assert saldo == 5, "no debe pisar el saldo del cierre manual de Ingenieros"


def test_correccion_dry_run_no_escribe_nada(db_temporal, client):
    conn = _conn(db_temporal)
    _crear_cierre(conn, "2026-06-01 10:00:00", {"20": {"saldo": 5, "gen_extra_al_corte": 0}},
                  [("20", "Empleado Roto", "redes", 3, 0)])
    _crear_cierre(conn, "2026-07-01 10:00:00", {"20": {"saldo": 12, "gen_extra_al_corte": 0}},
                  [("20", "Empleado Roto", "redes", 2, 0)])
    _set_saldo_inicial(conn, "20", "Empleado Roto", 14)
    conn.close()

    resp = client.get("/admin/corregir-cadena-completa-saldos-francos")
    data = resp.get_json()
    assert data["aplicado"] is False
    assert data["total_con_diferencia"] == 1

    conn = _conn(db_temporal)
    saldo = conn.execute(
        "SELECT saldo FROM francos_saldo_inicial WHERE legajo='20'"
    ).fetchone()["saldo"]
    conn.close()
    assert saldo == 14, "el dry-run no debe modificar nada"


def test_correccion_confirmada_corrige_solo_el_legajo_afectado(db_temporal, client):
    conn = _conn(db_temporal)
    _crear_cierre(conn, "2026-06-01 10:00:00", {"10": {"saldo": 5, "gen_extra_al_corte": 0}},
                  [("10", "Empleado Sano", "redes", 3, 0)])
    _crear_cierre(conn, "2026-07-01 10:00:00", {"10": {"saldo": 8, "gen_extra_al_corte": 0}},
                  [("10", "Empleado Sano", "redes", 2, 0)])
    _set_saldo_inicial(conn, "10", "Empleado Sano", 10)

    _crear_cierre(conn, "2026-06-01 10:00:00", {"20": {"saldo": 5, "gen_extra_al_corte": 0}},
                  [("20", "Empleado Roto", "redes", 3, 0)])
    pid2_roto = _crear_cierre(
        conn, "2026-07-01 10:00:00", {"20": {"saldo": 12, "gen_extra_al_corte": 0}},
        [("20", "Empleado Roto", "redes", 2, 0)]
    )
    _set_saldo_inicial(conn, "20", "Empleado Roto", 14)
    conn.close()

    resp = client.get("/admin/corregir-cadena-completa-saldos-francos?confirmar=si")
    data = resp.get_json()
    assert data["aplicado"] is True
    assert "backup" in data

    conn = _conn(db_temporal)
    fila_roto = conn.execute(
        "SELECT saldo, nota FROM francos_saldo_inicial WHERE legajo='20'"
    ).fetchone()
    fila_sano = conn.execute(
        "SELECT saldo FROM francos_saldo_inicial WHERE legajo='10'"
    ).fetchone()
    periodo_intacto = conn.execute(
        "SELECT estado FROM periodos WHERE id=?", (pid2_roto,)
    ).fetchone()
    conn.close()

    assert fila_roto["saldo"] == 10, "debe quedar en el valor recalculado, no en el declarado"
    assert "cadena completa" in fila_roto["nota"].lower()
    assert fila_sano["saldo"] == 10, "el legajo sano no debe tocarse"
    assert periodo_intacto["estado"] == "ACTIVO", "no debe anularse ningun cierre"
