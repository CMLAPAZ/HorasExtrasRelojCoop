# -*- coding: utf-8 -*-
"""
fecha_corte de francos_saldo_inicial debe representar la fecha/hora REAL
del cierre (periodos.cerrado_en), no fecha_hasta del período de horas
extras que se está cerrando.

Bug histórico (commit 666a365, 2026-06-03): la actualización automática de
francos_saldo_inicial al cerrar un período usaba fecha_hasta del período de
horas tanto para la columna fecha_corte como para la nota. Corregido en
c34f12e (2026-06-11): ahora usa _normalizar_cargado_en(ahora) = cerrado_en.

/admin/corregir-fecha-corte/<pid> corrige el dato histórico de cierres
hechos antes de c34f12e: actualiza únicamente fecha_corte (no saldo,
tomados_al_corte, gen_extra_al_corte, nota ni cargado_en), acotado a los
legajos de ese cierre, con backup previo de la DB.
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


def _crear_periodo(conn, cerrado_en, departamento, legajo, nombre,
                   fecha_desde="2026-05-04", fecha_hasta="2026-05-31", estado="ACTIVO"):
    """Inserta un cierre (periodos + un periodo_empleados) y devuelve su pid."""
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
        (cerrado_en, 1, 1, "periodo_test.json", fecha_desde, fecha_hasta, estado),
    )
    pid = cur.lastrowid
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
        "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, legajo, nombre, departamento, "0h", "0h", 0, 0, 0, "[]", 0),
    )
    conn.commit()
    return pid


def _crear_saldo_inicial(conn, legajo, nombre, saldo=0, fecha_corte="2026-05-31",
                          tomados_al_corte=0, gen_extra_al_corte=0,
                          nota="nota original", cargado_en="2026-06-08 10:17:54"):
    conn.execute(
        "INSERT INTO francos_saldo_inicial "
        "(legajo, nombre, saldo, nota, cargado_en, tomados_al_corte, gen_extra_al_corte, fecha_corte) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (legajo, nombre, saldo, nota, cargado_en, tomados_al_corte, gen_extra_al_corte, fecha_corte),
    )
    conn.commit()


# ──────────────────────────────────────────────────────────────
# 1. periodo_cerrar: fecha_corte = cerrado_en, no fecha_hasta del período
#    de horas (regresión del bug de la commit 666a365)
# ──────────────────────────────────────────────────────────────

def test_periodo_cerrar_fecha_corte_usa_cerrado_en_no_fecha_hasta(db_temporal, client, monkeypatch, tmp_path):
    leg, nombre = "133", "ZABALA ANTONIO"
    resumen = [{
        "legajo": leg, "nombre": nombre, "departamento": "Redes",
        "ot50": "1h00", "ot100": "0h", "comidas": 0, "francos": 0,
        "tardanzas": 0, "confirmado": True,
    }]
    meta = {
        "semana_actual": 1,
        "semanas": [{"numero": 1, "num_depto": 1, "departamento": "Redes",
                      "fecha_desde": "2026-05-25", "fecha_hasta": "2026-05-31"}],
    }
    monkeypatch.setattr(servidor, "_calcular_periodo", lambda *a, **kw: resumen)
    monkeypatch.setattr(servidor, "_cargar_metadata", lambda: meta)
    monkeypatch.setattr(servidor, "_guardar_metadata", lambda m: None)
    monkeypatch.setattr(servidor, "_guardar_sesion", lambda s: None)
    monkeypatch.setattr(servidor, "_sesion", {})
    monkeypatch.setattr(servidor, "_generar_pdf_francos_cierre", lambda *a, **kw: None)
    monkeypatch.setattr(servidor, "PERIODOS_DIR", tmp_path / "periodos")
    monkeypatch.setattr(servidor, "CONFIRM_DIR", tmp_path / "confirmaciones")

    resp = client.post("/periodo/cerrar", data={
        "desde": "1", "hasta": "1", "departamento": "Redes",
        "fecha_desde": "2026-05-25", "fecha_hasta": "2026-05-31",
    })
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    conn = _conn(db_temporal)
    periodo = conn.execute("SELECT * FROM periodos ORDER BY id DESC LIMIT 1").fetchone()
    assert periodo["fecha_hasta"] == "2026-05-31"

    cerrado_en = servidor._normalizar_cargado_en(periodo["cerrado_en"])

    si = conn.execute("SELECT * FROM francos_saldo_inicial WHERE legajo=?", (leg,)).fetchone()
    assert si is not None

    # Regla definitiva: fecha_corte = cerrado_en (fecha real del cierre),
    # NUNCA fecha_hasta del período de horas extras.
    assert si["fecha_corte"] == cerrado_en
    assert si["fecha_corte"] != periodo["fecha_hasta"]
    assert cerrado_en in si["nota"]
    assert "(2026-05-31)" not in si["nota"]


# ──────────────────────────────────────────────────────────────
# 2. /admin/corregir-fecha-corte/<pid>: GET es diagnóstico de solo lectura
# ──────────────────────────────────────────────────────────────

def test_diagnostico_pid_inexistente(db_temporal, client):
    resp = client.get("/admin/corregir-fecha-corte/999")
    assert resp.status_code == 404


def test_diagnostico_muestra_cambio_cuando_fecha_corte_es_fecha_hasta(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    pid = _crear_periodo(conn, "2026-06-08T10:17:49.110515", "Redes", leg, nombre,
                          fecha_desde="2026-05-04", fecha_hasta="2026-05-31")
    _crear_saldo_inicial(conn, leg, nombre, saldo=5, fecha_corte="2026-05-31",
                          tomados_al_corte=2, gen_extra_al_corte=1,
                          nota=f"Actualizado automáticamente al cerrar período #{pid} (2026-05-31)")

    resp = client.get(f"/admin/corregir-fecha-corte/{pid}")
    assert resp.status_code == 200
    diag = resp.get_json()

    assert diag["periodo_id"] == pid
    assert diag["fecha_hasta_periodo"] == "2026-05-31"
    assert diag["cerrado_en"] == "2026-06-08 10:17:49.110515"
    assert diag["legajos"] == [leg]
    assert diag["legajos_sin_registro_saldo_inicial"] == []
    assert diag["cambios"] == [{
        "legajo": leg,
        "fecha_corte_actual": "2026-05-31",
        "fecha_corte_nuevo": "2026-06-08 10:17:49.110515",
    }]

    # GET no escribe nada
    si = conn.execute("SELECT * FROM francos_saldo_inicial WHERE legajo=?", (leg,)).fetchone()
    assert si["fecha_corte"] == "2026-05-31"


def test_diagnostico_sin_cambios_si_fecha_corte_ya_es_cerrado_en(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    pid = _crear_periodo(conn, "2026-06-08T10:17:49.110515", "Redes", leg, nombre)
    _crear_saldo_inicial(conn, leg, nombre, fecha_corte="2026-06-08 10:17:49.110515")

    resp = client.get(f"/admin/corregir-fecha-corte/{pid}")
    diag = resp.get_json()
    assert diag["cambios"] == []


def test_diagnostico_reporta_legajos_sin_registro_saldo_inicial(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"
    pid = _crear_periodo(conn, "2026-06-08T10:17:49.110515", "Redes", leg, nombre)
    # Sin fila en francos_saldo_inicial para este legajo

    resp = client.get(f"/admin/corregir-fecha-corte/{pid}")
    diag = resp.get_json()
    assert diag["cambios"] == []
    assert diag["legajos_sin_registro_saldo_inicial"] == [leg]


# ──────────────────────────────────────────────────────────────
# 3. POST sin confirmar=si: no aplica nada
# ──────────────────────────────────────────────────────────────

def test_post_sin_confirmar_no_aplica(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    pid = _crear_periodo(conn, "2026-06-08T10:17:49.110515", "Redes", leg, nombre,
                          fecha_hasta="2026-05-31")
    _crear_saldo_inicial(conn, leg, nombre, fecha_corte="2026-05-31")

    resp = client.post(f"/admin/corregir-fecha-corte/{pid}")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Falta confirmar=si"

    si = conn.execute("SELECT * FROM francos_saldo_inicial WHERE legajo=?", (leg,)).fetchone()
    assert si["fecha_corte"] == "2026-05-31"

    # No se creó ningún backup
    assert list(db_temporal.parent.glob("cierres_backup_pre_fecha_corte_*.db")) == []


# ──────────────────────────────────────────────────────────────
# 4. POST ?confirmar=si: corrige SOLO fecha_corte, con backup, acotado a
#    los legajos del cierre, sin tocar saldo/tomados_al_corte/
#    gen_extra_al_corte/nota/cargado_en
# ──────────────────────────────────────────────────────────────

def test_post_confirmar_corrige_solo_fecha_corte_con_backup(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    pid = _crear_periodo(conn, "2026-06-08T10:17:49.110515", "Redes", leg, nombre,
                          fecha_desde="2026-05-04", fecha_hasta="2026-05-31")
    nota_original = f"Actualizado automáticamente al cerrar período #{pid} (2026-05-31)"
    _crear_saldo_inicial(conn, leg, nombre, saldo=5, fecha_corte="2026-05-31",
                          tomados_al_corte=2, gen_extra_al_corte=1,
                          nota=nota_original, cargado_en="2026-06-08 10:17:54")

    # Otro legajo, de OTRO cierre, con la misma fecha_corte "vieja" -- no
    # debe ser tocado por esta corrección (acotada a los legajos del pid).
    leg_otro, nombre_otro = "999", "OTRO EMPLEADO"
    _crear_periodo(conn, "2026-06-05T09:00:00.000000", "Administración", leg_otro, nombre_otro,
                    fecha_desde="2026-05-04", fecha_hasta="2026-05-31")
    _crear_saldo_inicial(conn, leg_otro, nombre_otro, saldo=3, fecha_corte="2026-05-31",
                          nota="otra nota", cargado_en="2026-06-05 09:00:05")

    resp = client.post(f"/admin/corregir-fecha-corte/{pid}?confirmar=si")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["cambios"] == [{
        "legajo": leg,
        "fecha_corte_actual": "2026-05-31",
        "fecha_corte_nuevo": "2026-06-08 10:17:49.110515",
    }]

    backup_path = body["backup"]
    from pathlib import Path
    assert Path(backup_path).exists()
    assert Path(backup_path).name.startswith(f"cierres_backup_pre_fecha_corte_{pid}_")

    si = conn.execute("SELECT * FROM francos_saldo_inicial WHERE legajo=?", (leg,)).fetchone()
    assert si["fecha_corte"] == "2026-06-08 10:17:49.110515"
    # Nada más cambia
    assert si["saldo"] == 5
    assert si["tomados_al_corte"] == 2
    assert si["gen_extra_al_corte"] == 1
    assert si["nota"] == nota_original
    assert si["cargado_en"] == "2026-06-08 10:17:54"

    # El legajo de otro cierre queda intacto
    si_otro = conn.execute("SELECT * FROM francos_saldo_inicial WHERE legajo=?", (leg_otro,)).fetchone()
    assert si_otro["fecha_corte"] == "2026-05-31"
    assert si_otro["saldo"] == 3


def test_post_confirmar_sin_cambios_no_crea_backup(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    pid = _crear_periodo(conn, "2026-06-08T10:17:49.110515", "Redes", leg, nombre)
    _crear_saldo_inicial(conn, leg, nombre, fecha_corte="2026-06-08 10:17:49.110515")

    resp = client.post(f"/admin/corregir-fecha-corte/{pid}?confirmar=si")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["mensaje"] == "Nada para corregir."

    assert list(db_temporal.parent.glob("cierres_backup_pre_fecha_corte_*.db")) == []


# ──────────────────────────────────────────────────────────────
# 5. Requiere autenticación
# ──────────────────────────────────────────────────────────────

def test_requiere_auth(db_temporal, client, monkeypatch):
    monkeypatch.setattr(servidor, "_autenticado", lambda: False)
    resp = client.get("/admin/corregir-fecha-corte/1")
    assert resp.status_code == 401
    resp = client.post("/admin/corregir-fecha-corte/1?confirmar=si")
    assert resp.status_code == 401
