# -*- coding: utf-8 -*-
"""
Ciclo cerrar -> anular -> volver a cerrar de un período (periodos / periodo_cerrar
/ periodo_anular), y la invariante central de negocio: el saldo final de un
cierre siempre debe coincidir con el saldo inicial (saldo_anterior) del
próximo cierre del mismo departamento.

_delta_francos_cierre calcula el delta propio de UN cierre puntual (solo lo
que quedó grabado en periodo_empleados.francos y francos_cierre_detalle bajo
ese periodo_id) -- a diferencia de _calcular_saldos(), que es el saldo "en
vivo" global usado para pantallas/reportes y que calcula los generados del
período activo en vivo con _calcular_periodo() (misma fuente que la pantalla
de Períodos), no leyendo la tabla-snapshot francos_semana_parcial -- esa
tabla podía quedar con filas residuales de semanas ya cerradas y duplicar en
pantalla lo que el cierre ya había dejado en el saldo. Usar _calcular_saldos()
para grabar el saldo de un cierre puntual mezcla datos de otro período/mes en
curso -- ver CLAUDE.md y el plan de rediseño de cierre de francos.
"""
import sqlite3

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
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    return conn


def _crear_periodo(conn, cerrado_en, departamento, legajo, nombre, estado="ACTIVO", francos=0):
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
        (cerrado_en, 1, 1, "periodo_test.json", "2026-01-01", "2026-01-07", estado),
    )
    pid = cur.lastrowid
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
        "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, legajo, nombre, departamento, "0h", "0h", 0, francos, 0, "[]", 0),
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
# 1. _delta_francos_cierre no mezcla un parcial de otro mes/semana en curso
#    (reproduce el bug real: la actualización automática de saldo usaba
#    _calcular_saldos(), que sí suma francos_semana_parcial de cualquier
#    depto/semana sin cerrar todavía)
# ──────────────────────────────────────────────────────────────

def test_delta_francos_cierre_ignora_parciales_de_otro_mes_en_curso(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "13", "GOMEZ MARIO"

    pid = _crear_periodo(conn, "2026-06-20T14:10:00.000000", "Administración", leg, nombre, francos=0)

    # Parcial de una semana de JULIO en curso, sin cerrar -- no debería
    # tener nada que ver con el cierre de junio (pid).
    conn.execute(
        "INSERT INTO francos_semana_parcial (legajo, nombre, departamento, semana_num, dias, guardado_en) "
        "VALUES (?,?,?,?,?,?)",
        (leg, nombre, "Administración", 99, 1, "2026-07-15 10:00:00"),
    )
    conn.commit()

    delta = servidor._delta_francos_cierre(conn, pid, {leg})
    assert delta[leg]["generados_periodo"] == 0
    assert delta[leg]["tomados_periodo"] == 0

    # Para contraste: _calcular_saldos() (la vista global "en vivo") ya no
    # lee francos_semana_parcial en absoluto -- calcula los generados del
    # período activo en vivo con _calcular_periodo(), igual que la pantalla
    # de Períodos. La fila insertada arriba en la tabla-snapshot (sin
    # ninguna confirmación/sesión real detrás) no debe generar ningún
    # "Generado" fantasma.
    saldos = servidor._calcular_saldos()
    saldo_leg = next(s for s in saldos if str(s["legajo"]) == leg)
    assert saldo_leg["generados"] == 0


def test_calcular_saldos_no_duplica_generados_con_parcial_residual_de_periodo_ya_cerrado(db_temporal):
    """Reproduce el bug real de producción (31/07/2026): un cierre ya
    absorbió los francos generados de sus semanas en periodo_empleados, pero
    francos_semana_parcial de esas mismas semanas no se había borrado (o
    quedó un residuo). _calcular_saldos() sumaba periodo_empleados.francos
    + esa fila residual, duplicando el "Generados" mostrado en pantalla para
    los 27 empleados de Redes por igual. Ahora _calcular_saldos() no lee
    francos_semana_parcial en absoluto -- calcula el período activo en vivo
    con _calcular_periodo(), así que un residuo en esa tabla-snapshot no
    puede volver a inflar el saldo."""
    conn = _conn(db_temporal)
    leg, nombre = "121", "CASTRILLON"

    # fecha_corte anterior a la fecha_hasta del cierre (2026-01-01/07), para
    # que ese cierre efectivamente cuente en gen_periodos_por_emp.
    conn.execute(
        "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, fecha_corte, cargado_en) "
        "VALUES (?,?,0,?,?)",
        (leg, nombre, "2025-12-01", "2025-12-01 00:00:00"),
    )
    conn.commit()

    # Cierre ya realizado: dejó 3 francos generados en periodo_empleados.
    _crear_periodo(conn, "2026-07-03T15:18:04.000000", "Redes", leg, nombre, francos=3)

    # Residuo de francos_semana_parcial de esas mismas semanas, que en el
    # incidente real no se había limpiado al cerrar.
    conn.execute(
        "INSERT INTO francos_semana_parcial (legajo, nombre, departamento, semana_num, dias, guardado_en) "
        "VALUES (?,?,?,?,?,?)",
        (leg, nombre, "Redes", 1, 3, "2026-07-01 10:00:00"),
    )
    conn.commit()

    saldos = servidor._calcular_saldos()
    saldo_leg = next(s for s in saldos if str(s["legajo"]) == leg)
    assert saldo_leg["generados"] == 3


def test_delta_francos_cierre_solo_cuenta_lo_propio_del_pid(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    pid1 = _crear_periodo(conn, "2026-05-20T12:00:00.000000", "Redes", leg, nombre, francos=2)
    _crear_franco(conn, leg, nombre, cargado_en="2026-05-15 10:00:00", fecha_desde="2026-05-10")
    servidor._snapshot_francos_cierre(conn, pid1, "2026-05-20 12:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    pid2 = _crear_periodo(conn, "2026-06-20T12:00:00.000000", "Redes", leg, nombre, francos=1)
    _crear_franco(conn, leg, nombre, cargado_en="2026-06-15 10:00:00", fecha_desde="2026-06-10")
    servidor._snapshot_francos_cierre(conn, pid2, "2026-06-20 12:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    delta1 = servidor._delta_francos_cierre(conn, pid1, {leg})
    delta2 = servidor._delta_francos_cierre(conn, pid2, {leg})
    assert delta1[leg] == {"generados_periodo": 2, "tomados_periodo": 1}
    assert delta2[leg] == {"generados_periodo": 1, "tomados_periodo": 1}


# ──────────────────────────────────────────────────────────────
# 2. Ciclo completo vía las rutas reales: cerrar -> anular -> volver a
#    cerrar el mismo rango preserva la cadena de saldos (idempotencia)
# ──────────────────────────────────────────────────────────────

def test_ciclo_cerrar_anular_recerrar_preserva_cadena_de_saldos(db_temporal, client, monkeypatch):
    leg, nombre, depto = "133", "ZABALA ANTONIO", "Redes"

    def _meta_con_semana():
        servidor._guardar_metadata({
            "semana_actual": 1,
            "semanas": [{
                "numero": 1, "num_depto": 1, "departamento": depto,
                "fecha_desde": "2026-06-01", "fecha_hasta": "2026-06-07",
            }],
        })

    _meta_con_semana()

    resumen_fijo = [{
        "legajo": leg, "nombre": nombre, "departamento": depto,
        "ot50": "0h", "ot100": "0h", "comidas": 0, "francos": 0, "tardanzas": 0,
        "semanas": [1], "confirmado": True, "pendientes": [], "dias": [],
        "excluido_ot": False, "liquida_ot": True, "observacion_liquidacion": "",
    }]
    monkeypatch.setattr(servidor, "_calcular_periodo",
                         lambda desde, hasta, departamento=None: resumen_fijo)

    conn = _conn(db_temporal)
    _crear_franco(conn, leg, nombre, cargado_en="2026-06-05 10:00:00", fecha_desde="2026-06-03", dias=1)
    conn.close()

    form = {"desde": "1", "hasta": "1", "departamento": depto,
            "fecha_desde": "2026-06-01", "fecha_hasta": "2026-06-07"}

    resp1 = client.post("/periodo/cerrar", data=form)
    assert resp1.status_code == 200, resp1.get_json()

    conn = _conn(db_temporal)
    pid1 = conn.execute("SELECT id FROM periodos ORDER BY id DESC LIMIT 1").fetchone()["id"]
    fila1 = conn.execute(
        "SELECT saldo, tomados_al_corte FROM francos_saldo_inicial WHERE legajo=?", (leg,)
    ).fetchone()
    assert fila1["saldo"] == -1          # 0 base + 0 generado - 1 tomado
    assert fila1["tomados_al_corte"] == 1
    estado_franco = conn.execute(
        "SELECT estado FROM francos_tomados WHERE legajo=?", (leg,)
    ).fetchone()["estado"]
    assert estado_franco == "Cerrado"
    conn.close()

    resp_anular = client.post(f"/periodos/anular/{pid1}", data={"motivo": "test"})
    assert resp_anular.status_code == 200, resp_anular.get_json()

    conn = _conn(db_temporal)
    fila_tras_anular = conn.execute(
        "SELECT saldo, tomados_al_corte FROM francos_saldo_inicial WHERE legajo=?", (leg,)
    ).fetchone()
    assert fila_tras_anular["saldo"] == 0
    assert fila_tras_anular["tomados_al_corte"] == 0
    estado_tras_anular = conn.execute(
        "SELECT estado FROM francos_tomados WHERE legajo=?", (leg,)
    ).fetchone()["estado"]
    assert estado_tras_anular == "Aprobado"
    conn.close()

    # Volver a cerrar el mismo rango -- hace falta re-agregar la semana
    # activa porque el primer cierre la sacó de metadata.json.
    _meta_con_semana()
    resp2 = client.post("/periodo/cerrar", data=form)
    assert resp2.status_code == 200, resp2.get_json()

    conn = _conn(db_temporal)
    pid2 = conn.execute("SELECT id FROM periodos ORDER BY id DESC LIMIT 1").fetchone()["id"]
    assert pid2 != pid1
    fila2 = conn.execute(
        "SELECT saldo, tomados_al_corte FROM francos_saldo_inicial WHERE legajo=?", (leg,)
    ).fetchone()
    assert fila2["saldo"] == fila1["saldo"]                    # idempotente
    assert fila2["tomados_al_corte"] == fila1["tomados_al_corte"]

    # La herramienta de verificación de cadena no debe reportar nada raro
    # entre estos dos cierres (pid1 está ANULADO, no forma parte de la
    # cadena de cierres activos).
    resp_verif = client.get("/admin/verificar-cadena-saldos-francos")
    diag = resp_verif.get_json()
    assert diag["desajustes"] == []
    conn.close()


# ──────────────────────────────────────────────────────────────
# 3. Revertir por francos_tomados_id no es ambiguo con duplicados exactos
#    (misma tupla legajo/tipo/fechas/días capturados por el mismo cierre)
# ──────────────────────────────────────────────────────────────

def test_revertir_por_id_no_ambiguo_con_duplicados_exactos(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    id1 = _crear_franco(conn, leg, nombre, cargado_en="2026-06-01 10:00:00", fecha_desde="2026-06-01", dias=1)
    id2 = _crear_franco(conn, leg, nombre, cargado_en="2026-06-01 10:00:00", fecha_desde="2026-06-01", dias=1)

    pid = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    fecha_corte = servidor._normalizar_cargado_en("2026-06-10T12:00:00.000000")
    servidor._snapshot_francos_cierre(conn, pid, fecha_corte, legajos=[leg], departamento="redes")
    conn.commit()

    estados = {r["id"]: r["estado"] for r in conn.execute("SELECT id, estado FROM francos_tomados")}
    assert estados[id1] == "Cerrado" and estados[id2] == "Cerrado"

    revertidos = servidor._revertir_estado_francos_cierre(conn, pid)
    conn.commit()
    assert revertidos == 2

    estados_post = {r["id"]: r["estado"] for r in conn.execute("SELECT id, estado FROM francos_tomados")}
    assert estados_post[id1] == "Aprobado" and estados_post[id2] == "Aprobado"


# ──────────────────────────────────────────────────────────────
# 4. /francos/eliminar y /francos/aprobar bloquean un franco 'Cerrado' por
#    el mecanismo de periodos (no solo el de cierres_francos)
# ──────────────────────────────────────────────────────────────

def test_eliminar_bloqueado_para_franco_cerrado_por_periodo(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"
    fid = _crear_franco(conn, leg, nombre, cargado_en="2026-06-01 10:00:00", fecha_desde="2026-06-01", dias=1)
    conn.execute("UPDATE francos_tomados SET estado='Cerrado' WHERE id=?", (fid,))
    conn.commit()

    resp = client.post(f"/francos/eliminar/{fid}", data={})
    assert resp.status_code in (301, 302)
    assert "error=movimiento_cerrado" in resp.headers["Location"]

    estado = conn.execute("SELECT estado FROM francos_tomados WHERE id=?", (fid,)).fetchone()["estado"]
    assert estado == "Cerrado"


def test_aprobar_bloqueado_para_franco_cerrado_por_periodo(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"
    fid = _crear_franco(conn, leg, nombre, cargado_en="2026-06-01 10:00:00", fecha_desde="2026-06-01",
                         dias=1, estado="Pendiente")
    conn.execute("UPDATE francos_tomados SET estado='Cerrado' WHERE id=?", (fid,))
    conn.commit()

    resp = client.post(f"/francos/aprobar/{fid}", data={})
    assert resp.status_code in (301, 302)
    assert "error=movimiento_cerrado" in resp.headers["Location"]

    estado = conn.execute("SELECT estado FROM francos_tomados WHERE id=?", (fid,)).fetchone()["estado"]
    assert estado == "Cerrado"
