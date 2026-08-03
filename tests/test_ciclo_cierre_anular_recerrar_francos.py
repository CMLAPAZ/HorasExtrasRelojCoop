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
import json
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


def _crear_periodo(conn, cerrado_en, departamento, legajo, nombre, estado="ACTIVO", francos=0,
                    fecha_desde="2026-01-01", fecha_hasta="2026-01-07"):
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
        (cerrado_en, 1, 1, "periodo_test.json", fecha_desde, fecha_hasta, estado),
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


def test_calcular_saldos_no_duplica_generados_con_confirmacion_archivada_readoptada_por_fecha(db_temporal):
    """Reproduce el incidente real de producción (31/07/2026, Castrillón
    +6 en vez de +3): _resolver_semana_confirmacion() reamarra por fecha una
    confirmación archivada de un cierre YA cerrado (no anulado) cuando una
    semana nueva activa se solapa en fechas con ese cierre viejo -- ver su
    docstring y el de _archivos_confirmacion(). Sin filtrar por fecha_corte
    por-empleado en _calcular_saldos(), ese día ya absorbido en el cierre
    (reflejado en el saldo_inicial actualizado automáticamente al cerrar) se
    contaba una segunda vez porque _calcular_periodo() la "readopta" como si
    fuera del período activo en curso."""
    conn = _conn(db_temporal)
    leg, nombre = "121", "CASTRILLON DIEGO"

    cerrado_en = "2026-07-03T15:18:04.000000"
    conn.execute(
        "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, fecha_corte, cargado_en) "
        "VALUES (?,?,13,?,?)",
        (leg, nombre, cerrado_en, cerrado_en),
    )
    # Ventana real del cierre de junio -- incluye el 2026-06-15, la fecha del
    # día readoptado más abajo, para que el chequeo por ventana (no por
    # fecha_corte a secas) siga reconociéndolo como ya absorbido.
    _crear_periodo(conn, cerrado_en, "Redes", leg, nombre, francos=3,
                    fecha_desde="2026-06-09", fecha_hasta="2026-06-15")
    conn.commit()

    # Semana activa nueva (período de julio en curso), con un rango de
    # fechas que se solapa con el cierre de junio ya cerrado.
    servidor._guardar_metadata({
        "semana_actual": 99,
        "semanas": [{
            "numero": 99, "num_depto": 5, "departamento": "Redes",
            "fecha_desde": "2026-06-01", "fecha_hasta": "2026-07-31",
            "archivo": "semana_99.csv",
        }],
    })

    # Confirmación archivada del cierre de junio, con su número de semana
    # original (1) que ya no existe en la metadata activa -- por eso
    # _resolver_semana_confirmacion() cae al fallback por fecha.
    servidor.CONFIRM_DIR.mkdir(exist_ok=True, parents=True)
    (servidor.CONFIRM_DIR / "vieja.json").write_text(json.dumps({
        "legajo": leg, "nombre": nombre, "departamento": "Redes", "semana": 1,
        "confirmado_en": "2026-06-16T10:00:00",
        "dias": [{"fecha": "2026-06-15", "franco": 1, "ot50": "00:00:00",
                   "ot100": "00:00:00", "comida": 0, "tiene_ot": True}],
        "totales": {"ot50": "0h", "ot100": "0h", "comidas": 0, "francos": 1, "tardanzas": 0},
    }, ensure_ascii=False), encoding="utf-8")

    saldos = servidor._calcular_saldos()
    saldo_leg = next(s for s in saldos if str(s["legajo"]) == leg)
    assert saldo_leg["generados"] == 0


def test_calcular_saldos_no_tapa_franco_del_periodo_abierto_por_recierre_tardio(db_temporal):
    """Reproduce el incidente real de producción (03/08/2026, Administración
    / GOMEZ MARIO): el cierre #6 cubría datos hasta 2026-06-28 pero, por
    haberse anulado y recerrado, se terminó de cerrar recién el 2026-07-20
    (cerrado_en). fecha_corte quedó en esa fecha tardía. El período
    siguiente (todavía abierto) ya se venía cargando en paralelo y generó un
    franco real el 2026-07-04 -- anterior a fecha_corte (07-20) pero
    POSTERIOR a la ventana de datos del cierre #6 (que terminaba el 06-28).
    Con el filtro viejo (día <= fecha_corte a secas) ese franco desaparecía
    de "Generados" en Saldos aunque sí aparecía en Períodos/Historial.
    Ahora el filtro compara contra la ventana fecha_desde..fecha_hasta de
    cada período ACTIVO ya cerrado, no contra fecha_corte."""
    conn = _conn(db_temporal)
    leg, nombre = "13", "GOMEZ MARIO"
    cerrado_tardio = "2026-07-20T14:10:32.244725"

    conn.execute(
        "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, fecha_corte, cargado_en) "
        "VALUES (?,?,25,?,?)",
        (leg, nombre, cerrado_tardio, "2026-07-21 09:58:07"),
    )
    # Cierre #6: ventana de datos hasta 2026-06-28, pero cerrado (cerrado_en)
    # recién el 2026-07-20 tras un ciclo anular/recerrar.
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
        (cerrado_tardio, 1, 4, "periodo_test.json", "2026-06-01", "2026-06-28", "ACTIVO"),
    )
    pid = cur.lastrowid
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
        "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, leg, nombre, "Administración", "0h", "0h", 0, 0, 0, "[]", 0),
    )
    conn.commit()

    # Período nuevo, todavía abierto (semanas 1-4, 2026-06-29 al 2026-07-26),
    # cargándose en paralelo mientras el cierre #6 seguía sin cerrarse.
    servidor._guardar_metadata({
        "semana_actual": 50,
        "semanas": [{
            "numero": 50, "num_depto": 1, "departamento": "Administración",
            "fecha_desde": "2026-06-29", "fecha_hasta": "2026-07-05",
            "archivo": "semana_50.csv",
        }],
    })
    servidor.CONFIRM_DIR.mkdir(exist_ok=True, parents=True)
    (servidor.CONFIRM_DIR / "nueva.json").write_text(json.dumps({
        "legajo": leg, "nombre": nombre, "departamento": "Administración", "semana": 50,
        "confirmado_en": "2026-07-05T10:00:00",
        "dias": [{"fecha": "2026-07-04", "franco": 1, "ot50": "00:00:00",
                   "ot100": "04:00:00", "comida": 0, "tiene_ot": True}],
        "totales": {"ot50": "0h", "ot100": "4h", "comidas": 0, "francos": 1, "tardanzas": 0},
    }, ensure_ascii=False), encoding="utf-8")

    saldos = servidor._calcular_saldos()
    saldo_leg = next(s for s in saldos if str(s["legajo"]) == leg)
    assert saldo_leg["generados"] == 1


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


# ──────────────────────────────────────────────────────────────
# 5. Auditoría de francos_saldo_inicial (triggers) + sincronización desde
#    cierres_francos -- reproduce el incidente Calvet/Telefonía (03/08/2026):
#    un cierre manual dejó saldo_final=8 pero francos_saldo_inicial quedó en
#    7 por una escritura fuera del mecanismo de cierre, sin registro de
#    quién la hizo.
# ──────────────────────────────────────────────────────────────

def test_trigger_auditoria_captura_cualquier_escritura_a_saldo_inicial(db_temporal):
    """Los triggers deben registrar la escritura sin importar el camino:
    acá se escribe directo por SQL, sin pasar por ninguna ruta de la app,
    simulando una edición fuera de los mecanismos conocidos."""
    conn = _conn(db_temporal)
    leg, nombre = "18", "CALVET SILVIA PATRICIA"

    conn.execute(
        "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, nota, cargado_en) "
        "VALUES (?,?,8,'carga inicial de prueba','2026-07-08 14:10:00')",
        (leg, nombre),
    )
    conn.commit()

    conn.execute("UPDATE francos_saldo_inicial SET saldo=7 WHERE legajo=?", (leg,))
    conn.commit()

    historial = conn.execute(
        "SELECT * FROM francos_saldo_inicial_auditoria WHERE legajo=? ORDER BY id", (leg,)
    ).fetchall()
    assert len(historial) == 2
    assert historial[0]["accion"] == "INSERT" and historial[0]["saldo_nuevo"] == 8
    assert historial[1]["accion"] == "UPDATE"
    assert historial[1]["saldo_anterior"] == 8
    assert historial[1]["saldo_nuevo"] == 7


def test_sincronizar_saldo_inicial_desde_cierre_francos_corrige_drift(db_temporal, client):
    """Reproduce el incidente real: cierre manual de Telefonía deja
    saldo_final=8 para Calvet (vía la ruta real /francos/cierre/nuevo, con
    su base_anterior/saldo_anterior propios), y después algo -- fuera del
    mecanismo de cierre -- pisa francos_saldo_inicial.saldo a 7. La ruta de
    sincronización debe detectar el drift contra ese mismo cierre y, con
    ?confirmar=si, restaurarlo a 8 -- quedando además registrado en
    francos_saldo_inicial_auditoria."""
    conn = _conn(db_temporal)
    leg, nombre = "18", "CALVET SILVIA PATRICIA"

    conn.execute(
        "INSERT INTO empleados_extra (legajo, nombre, departamento, activo) VALUES (?,?,?,1)",
        (leg, nombre, "Telefonia"),
    )
    conn.execute(
        "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, nota, cargado_en) "
        "VALUES (?,?,8,'saldo previo al cierre','2026-06-01 00:00:00')",
        (leg, nombre),
    )
    conn.commit()

    resp = client.post("/francos/cierre/nuevo", data={
        "departamento": "Telefonía", "fecha_hasta": "2026-07-08",
    })
    assert resp.status_code == 200, resp.get_json()
    cid = resp.get_json()["id"]

    fila = conn.execute("SELECT saldo FROM francos_saldo_inicial WHERE legajo=?", (leg,)).fetchone()
    assert fila["saldo"] == 8          # el cierre en sí quedó bien

    # Drift fuera de mecanismo: algo pisa el saldo en vivo a 7 sin cierre nuevo.
    conn.execute("UPDATE francos_saldo_inicial SET saldo=7 WHERE legajo=?", (leg,))
    conn.commit()

    resp_dry = client.get(f"/admin/sincronizar-saldo-inicial-desde-cierre-francos/{cid}")
    data_dry = resp_dry.get_json()
    assert data_dry["aplicado"] is False
    diffs = {d["legajo"]: d for d in data_dry["diferencias"]}
    assert leg in diffs
    assert diffs[leg]["actual"]["saldo"] == 7
    assert diffs[leg]["correcto"]["saldo"] == 8

    fila_sin_tocar = conn.execute("SELECT saldo FROM francos_saldo_inicial WHERE legajo=?", (leg,)).fetchone()
    assert fila_sin_tocar["saldo"] == 7    # dry-run no escribe nada

    resp_aplicar = client.get(f"/admin/sincronizar-saldo-inicial-desde-cierre-francos/{cid}?confirmar=si")
    data_aplicar = resp_aplicar.get_json()
    assert data_aplicar["legajos_corregidos"] == [leg]

    fila_final = conn.execute("SELECT saldo FROM francos_saldo_inicial WHERE legajo=?", (leg,)).fetchone()
    assert fila_final["saldo"] == 8

    historial = conn.execute(
        "SELECT * FROM francos_saldo_inicial_auditoria WHERE legajo=? ORDER BY id", (leg,)
    ).fetchall()
    ultima = historial[-1]
    assert ultima["saldo_anterior"] == 7 and ultima["saldo_nuevo"] == 8
    assert "sincronizado" in ultima["nota_nueva"].lower()


def test_corregir_saldo_inicial_manual_requiere_motivo_y_es_dry_run_por_default(db_temporal, client):
    """Ruta pensada para corregir a mano un legajo puntual (ej. Calvet, cuyo
    cierre de origen no tiene base_anterior y no se puede sincronizar con
    /admin/sincronizar-saldo-inicial-desde-cierre-francos) cuando hay
    evidencia externa confiable del valor correcto. Exige motivo, no aplica
    sin ?confirmar=si, y deja rastro en francos_saldo_inicial_auditoria."""
    conn = _conn(db_temporal)
    leg, nombre = "18", "CALVET SILVIA PATRICIA"
    conn.execute(
        "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, nota, cargado_en) "
        "VALUES (?,?,7,'nota original','2026-07-08 14:09:22')",
        (leg, nombre),
    )
    conn.commit()

    resp_sin_motivo = client.get(f"/admin/corregir-saldo-inicial/{leg}?saldo=8")
    assert resp_sin_motivo.status_code == 400

    resp_dry = client.get(f"/admin/corregir-saldo-inicial/{leg}?saldo=8&motivo=restaurado+segun+cierre+5")
    assert resp_dry.get_json()["aplicado"] is False
    fila_sin_tocar = conn.execute("SELECT saldo FROM francos_saldo_inicial WHERE legajo=?", (leg,)).fetchone()
    assert fila_sin_tocar["saldo"] == 7

    resp_aplicar = client.get(
        f"/admin/corregir-saldo-inicial/{leg}?saldo=8&motivo=restaurado+segun+cierre+5&confirmar=si"
    )
    assert resp_aplicar.get_json()["aplicado"] is True

    fila_final = conn.execute("SELECT saldo, nota FROM francos_saldo_inicial WHERE legajo=?", (leg,)).fetchone()
    assert fila_final["saldo"] == 8
    assert "restaurado segun cierre 5" in fila_final["nota"]

    historial = conn.execute(
        "SELECT * FROM francos_saldo_inicial_auditoria WHERE legajo=? ORDER BY id", (leg,)
    ).fetchall()
    ultima = historial[-1]
    assert ultima["saldo_anterior"] == 7 and ultima["saldo_nuevo"] == 8
