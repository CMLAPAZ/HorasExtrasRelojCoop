# -*- coding: utf-8 -*-
"""
/admin/diagnostico-francos — diagnóstico de SOLO LECTURA del estado de los
snapshots de francos (Mecanismo A: periodos/francos_cierre_detalle, y
Mecanismo B: cierres_francos).

La ruta reutiliza _seleccionar_francos_ventana_cierre (la misma fuente de
verdad que /admin/corregir-francos-cierre) para estimar cuántos registros
"corresponderían" a cada cierre, sin escribir nada en la base."""
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


def _crear_periodo(conn, cerrado_en, departamento, legajo, nombre, estado="ACTIVO"):
    """Inserta un cierre (periodos + un periodo_empleados) y devuelve su pid."""
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
        (cerrado_en, 1, 1, "periodo_test.json", "2026-01-01", "2026-01-07", estado),
    )
    pid = cur.lastrowid
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
        "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, legajo, nombre, departamento, "0h", "0h", 0, 0, 0, "[]", 0),
    )
    conn.commit()
    return pid


def _crear_franco(conn, legajo, nombre, cargado_en, fecha_desde, dias=1,
                   tipo="UNICO", fecha_hasta="", estado="Aprobado"):
    cur = conn.execute(
        "INSERT INTO francos_tomados (legajo, nombre, tipo, fecha_desde, fecha_hasta, "
        "fechas_sueltas, dias, estado, cargado_en) VALUES (?,?,?,?,?,?,?,?,?)",
        (legajo, nombre, tipo, fecha_desde, fecha_hasta or fecha_desde, "[]", dias, estado, cargado_en),
    )
    conn.commit()
    return cur.lastrowid


# ──────────────────────────────────────────────────────────────
# 1. DB vacía: estructura básica del JSON, sin romper
# ──────────────────────────────────────────────────────────────

def test_diagnostico_db_vacia_estructura_basica(db_temporal, client):
    resp = client.get("/admin/diagnostico-francos")
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["periodos"]["total"] == 0
    assert data["periodos"]["por_departamento"] == {}
    assert data["periodos"]["con_snapshot"] == {}
    assert data["periodos"]["snapshot_vacio"] == {}
    assert data["periodos"]["requieren_correccion"] == []
    assert data["periodos"]["detalle"] == []

    assert data["cierres_francos_manuales"]["total"] == 0
    assert "nota" in data["cierres_francos_manuales"]

    assert data["cierres_posteriores_afectados_por_correccion"] == []
    assert data["inconsistencias_cadena_saldos"] == []


# ──────────────────────────────────────────────────────────────
# 2. Un cierre con snapshot OK y otro con snapshot vacío (sin
#    correcciones pendientes) — agregados por departamento
# ──────────────────────────────────────────────────────────────

def test_diagnostico_snapshot_ok_vs_snapshot_vacio(db_temporal, client):
    conn = _conn(db_temporal)
    leg1, nom1 = "133", "ZABALA ANTONIO"
    leg2, nom2 = "134", "OTRO EMPLEADO"

    _crear_franco(conn, leg1, nom1, cargado_en="2026-05-30 10:00:00", fecha_desde="2026-05-15")

    pid1 = _crear_periodo(conn, "2026-06-01 12:00:00", "Redes", leg1, nom1)
    servidor._snapshot_francos_cierre(conn, pid1, "2026-06-01 12:00:00", legajos=[leg1], departamento="Redes")
    conn.commit()

    pid2 = _crear_periodo(conn, "2026-06-08 12:00:00", "Redes", leg2, nom2)
    conn.commit()

    resp = client.get("/admin/diagnostico-francos")
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["periodos"]["total"] == 2
    assert data["periodos"]["por_departamento"]["Redes"] == 2
    assert data["periodos"]["con_snapshot"]["Redes"] == 1
    assert data["periodos"]["snapshot_vacio"]["Redes"] == 1
    assert data["periodos"]["legajos_participantes_por_departamento"]["Redes"] == 2

    por_id = {p["periodo_id"]: p for p in data["periodos"]["detalle"]}
    assert por_id[pid1]["registros_snapshot"] == 1
    assert por_id[pid1]["snapshot_vacio"] is False
    assert por_id[pid1]["requiere_correccion"] is False

    assert por_id[pid2]["registros_snapshot"] == 0
    assert por_id[pid2]["snapshot_vacio"] is True
    assert por_id[pid2]["requiere_correccion"] is False

    assert data["periodos"]["requieren_correccion"] == []
    assert data["cierres_posteriores_afectados_por_correccion"] == []


# ──────────────────────────────────────────────────────────────
# 3. Cierre sin snapshot y con un franco que le correspondería:
#    requiere_correccion=True, y la ruta no escribe nada
# ──────────────────────────────────────────────────────────────

def test_diagnostico_requiere_correccion_no_escribe_nada(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nom = "133", "ZABALA ANTONIO"

    franco_id = _crear_franco(conn, leg, nom, cargado_en="2026-06-05 10:00:00", fecha_desde="2026-05-20")
    pid = _crear_periodo(conn, "2026-06-10 12:00:00", "Redes", leg, nom)
    conn.commit()

    resp = client.get("/admin/diagnostico-francos")
    assert resp.status_code == 200
    data = resp.get_json()

    por_id = {p["periodo_id"]: p for p in data["periodos"]["detalle"]}
    info = por_id[pid]
    assert info["registros_snapshot"] == 0
    assert info["snapshot_vacio"] is True
    assert info["registros_correctos_estimados"] == 1
    assert info["registros_faltantes_estimados"] == 1
    assert info["requiere_correccion"] is True
    assert info["legacy_sin_cargado_en"] == 0
    assert info["ya_corregido_en"] == ""

    assert [p["periodo_id"] for p in data["periodos"]["requieren_correccion"]] == [pid]

    # La ruta es de SOLO LECTURA: no debe haber escrito el snapshot ni
    # haber marcado el franco como 'Cerrado'.
    detalle = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid,)).fetchall()
    assert detalle == []
    franco = conn.execute("SELECT estado FROM francos_tomados WHERE id=?", (franco_id,)).fetchone()
    assert franco["estado"] == "Aprobado"


# ──────────────────────────────────────────────────────────────
# 4. Cierre que requiere corrección y un cierre posterior del mismo
#    depto: aparece en cierres_posteriores_afectados_por_correccion
# ──────────────────────────────────────────────────────────────

def test_diagnostico_cierres_posteriores_afectados(db_temporal, client):
    conn = _conn(db_temporal)
    leg1, nom1 = "133", "ZABALA ANTONIO"
    leg2, nom2 = "134", "OTRO EMPLEADO"

    _crear_franco(conn, leg1, nom1, cargado_en="2026-05-30 10:00:00", fecha_desde="2026-05-15")
    pid1 = _crear_periodo(conn, "2026-06-01 12:00:00", "Redes", leg1, nom1)
    conn.commit()

    pid2 = _crear_periodo(conn, "2026-06-08 12:00:00", "Redes", leg2, nom2)
    conn.commit()

    resp = client.get("/admin/diagnostico-francos")
    assert resp.status_code == 200
    data = resp.get_json()

    afectados = {a["periodo_id"]: a for a in data["cierres_posteriores_afectados_por_correccion"]}
    assert pid1 in afectados
    assert afectados[pid1]["departamento"] == "Redes"
    assert afectados[pid1]["registros_faltantes_estimados"] == 1
    assert afectados[pid1]["periodos_posteriores_mismo_depto"] == [pid2]
    assert pid2 not in afectados


# ──────────────────────────────────────────────────────────────
# 5. Mecanismo B (cierres_francos): conteos por departamento, sin
#    snapshot inmutable
# ──────────────────────────────────────────────────────────────

def test_diagnostico_cierres_francos_manuales_por_depto(db_temporal, client):
    conn = _conn(db_temporal)
    conn.execute(
        "INSERT INTO cierres_francos (cerrado_en, departamento, fecha_hasta, total_dias, estado) "
        "VALUES (?,?,?,?,?)",
        ("2026-06-05 12:00:00", "Guardias", "2026-06-05", 3, "ACTIVO"),
    )
    conn.execute(
        "INSERT INTO empleados_extra (legajo, nombre, departamento, activo) VALUES (?,?,?,?)",
        ("113", "MAYDANA", "Guardias", 1),
    )
    conn.commit()

    resp = client.get("/admin/diagnostico-francos")
    assert resp.status_code == 200
    data = resp.get_json()

    cf = data["cierres_francos_manuales"]
    assert cf["total"] == 1
    assert cf["por_departamento"]["Guardias"] == 1
    assert cf["legajos_participantes_por_departamento"]["Guardias"] == 1
    assert "snapshot inmutable" in cf["nota"]


# ──────────────────────────────────────────────────────────────
# 6. Inconsistencia en cadena de saldos: francos_saldo_inicial con
#    fecha_corte distinta al último cierre ACTIVO del depto
# ──────────────────────────────────────────────────────────────

def test_diagnostico_inconsistencia_cadena_saldos(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nom = "133", "ZABALA ANTONIO"
    pid = _crear_periodo(conn, "2026-06-01 12:00:00", "Redes", leg, nom)
    conn.execute(
        "UPDATE francos_saldo_inicial SET saldo=2, fecha_corte='2026-05-01' WHERE legajo=?",
        (leg,),
    )
    if conn.execute("SELECT changes()").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, fecha_corte) VALUES (?,?,?,?)",
            (leg, nom, 2, "2026-05-01"),
        )
    conn.commit()

    resp = client.get("/admin/diagnostico-francos")
    assert resp.status_code == 200
    data = resp.get_json()

    inconsistencias = {i["legajo"]: i for i in data["inconsistencias_cadena_saldos"]}
    assert leg in inconsistencias
    assert inconsistencias[leg]["departamento"] == "Redes"
    assert inconsistencias[leg]["fecha_corte_saldo_inicial"] == "2026-05-01"
    assert inconsistencias[leg]["ultimo_cierre_id"] == pid
    assert inconsistencias[leg]["ultimo_cierre_cerrado_en"] == "2026-06-01"


# ──────────────────────────────────────────────────────────────
# 7. Requiere autenticación
# ──────────────────────────────────────────────────────────────

def test_diagnostico_requiere_auth(db_temporal, client, monkeypatch):
    monkeypatch.setattr(servidor, "_autenticado", lambda: False)
    resp = client.get("/admin/diagnostico-francos")
    assert resp.status_code == 401
