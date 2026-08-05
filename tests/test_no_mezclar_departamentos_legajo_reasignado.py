# -*- coding: utf-8 -*-
"""
Regla número uno del proyecto: nunca mezclar departamentos. Incidente real
(05/08/2026): "en el detalle de francos tomados me junta los ingenieros
con redes a partir de julio" -- los legajos 100/101 (Mancioni, Gatti)
tienen filas viejas de periodo_empleados con departamento='Redes' de
cuando procesaban por fichadas, antes de pasar a Ingenieros en julio 2026.
Varias rutas armaban su lista de "legajos de este depto" con
`SELECT DISTINCT legajo FROM periodo_empleados WHERE departamento=?`, que
es un snapshot histórico que nunca se actualiza -- así que esos legajos
seguían apareciendo bajo "Redes" para siempre, mezclando su actividad
NUEVA como Ingenieros (francos_tomados recientes) en el detalle de Redes.

Fix: _legajos_actuales_del_depto() usa _empleados_conocidos() (la fuente
de verdad vigente, que prioriza empleados_extra para 100/101) en vez del
snapshot histórico, para cualquier consulta que no sea sobre un cierre ya
cerrado puntual (periodo_id=?, que sí debe seguir siendo el snapshot).
"""
import pytest

import servidor


@pytest.fixture
def db_temporal(tmp_path, monkeypatch):
    db_file = tmp_path / "cierres_test.db"
    monkeypatch.setattr(servidor, "DATOS_DIR", tmp_path)
    monkeypatch.setattr(servidor, "DB_FILE", db_file)
    monkeypatch.setattr(servidor, "SEMANAS_DIR", tmp_path / "semanas")
    monkeypatch.setattr(servidor, "PERIODOS_DIR", tmp_path / "periodos")
    monkeypatch.setattr(servidor, "CONFIRM_DIR", tmp_path / "confirmaciones")
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
    import sqlite3
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    return conn


def _preparar_legajo_reasignado(db_file):
    """Reproduce el estado real: legajo 100 con un cierre viejo de Redes
    (periodo_empleados) y hoy activo como Ingenieros (empleados_extra)."""
    conn = _conn(db_file)
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
        ("2026-05-14T09:00:00", 1, 1, "periodo_viejo.json", "2026-05-04", "2026-05-11", "ACTIVO"),
    )
    pid = cur.lastrowid
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
        "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, "100", "MANCIONI MARTIN", "Redes", "0h", "0h", 0, 0, 0, "[]", 0),
    )
    # Empleado de verdad de Redes, para que el depto no quede vacío.
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
        "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, "133", "ZABALA ANTONIO", "Redes", "0h", "0h", 0, 0, 0, "[]", 0),
    )
    # _init_db() ya inserta 100/101 como Ingenieros (INSERT OR IGNORE); nos
    # aseguramos del estado esperado con upsert en vez de asumir que la fila
    # no existe.
    conn.execute("""
        INSERT INTO empleados_extra (legajo, nombre, departamento, activo)
        VALUES (?,?,?,1)
        ON CONFLICT(legajo) DO UPDATE SET
            nombre=excluded.nombre, departamento=excluded.departamento, activo=1
    """, ("100", "MANCIONI MARTIN", "Ingenieros"))
    # Actividad NUEVA de Mancioni, ya como Ingenieros -- esta es la que no
    # debe aparecer en el detalle de Redes.
    conn.execute(
        "INSERT INTO francos_tomados (legajo, nombre, tipo, fecha_desde, fecha_hasta, "
        "fechas_sueltas, dias, estado, cargado_en) VALUES (?,?,?,?,?,?,?,?,?)",
        ("100", "MANCIONI MARTIN", "UNICO", "2026-07-20", "2026-07-20", "[]", 1, "Aprobado", "2026-07-20 10:00:00"),
    )
    conn.commit()
    conn.close()
    return pid


def test_legajos_actuales_del_depto_no_incluye_reasignado(db_temporal):
    _preparar_legajo_reasignado(db_temporal)

    legajos_redes = servidor._legajos_actuales_del_depto("redes")
    legajos_ingenieros = servidor._legajos_actuales_del_depto("ingenieros")

    assert "100" not in legajos_redes, "Mancioni ya no es de Redes, no debe aparecer ahí"
    assert "133" in legajos_redes
    assert "100" in legajos_ingenieros


def test_francos_pdf_depto_redes_no_incluye_franco_de_ingenieros_reasignado(db_temporal, client, monkeypatch):
    """El PDF de detalle de Redes no debe traer el franco tomado de
    Mancioni cargado en julio como Ingenieros -- antes lo hacía porque la
    consulta de legajos usaba el snapshot histórico de periodo_empleados."""
    _preparar_legajo_reasignado(db_temporal)

    capturado = {}
    def _fake_pdf(pid, francos_list, fecha_hasta, **kwargs):
        capturado["francos_list"] = francos_list
        (servidor.Path("reportes")).mkdir(exist_ok=True)
        p = servidor.Path("reportes") / f"francos_cierre_{pid}_x.pdf"
        p.write_bytes(b"%PDF-1.4 fake")
        return p
    monkeypatch.setattr(servidor, "_generar_pdf_francos_cierre", _fake_pdf)

    resp = client.get("/francos/pdf_depto?depto=redes")
    assert resp.status_code == 200, resp.get_data(as_text=True)

    legajos_en_pdf = {f["legajo"] for f in capturado["francos_list"]}
    assert "100" not in legajos_en_pdf, "El detalle de Redes no debe incluir el franco de Mancioni (ahora Ingenieros)"


def test_francos_cierre_nuevo_rechaza_redes_y_administracion(db_temporal, client):
    """El cierre manual (mecanismo cierres_francos) es exclusivo de
    Guardias/Internet/Telefonía/Ingenieros -- Redes y Administración se
    cierran desde Períodos. Antes nada lo impedía: se podía cerrar "Redes"
    ahí y arrastrar legajos reasignados (100/101) por el mismo bug de
    snapshot histórico."""
    resp_redes = client.post("/francos/cierre/nuevo", data={
        "departamento": "Redes", "fecha_hasta": "2026-07-08",
    })
    assert resp_redes.status_code == 400
    assert "Períodos" in resp_redes.get_json()["error"]

    resp_admin = client.post("/francos/cierre/nuevo", data={
        "departamento": "Administración", "fecha_hasta": "2026-07-08",
    })
    assert resp_admin.status_code == 400
