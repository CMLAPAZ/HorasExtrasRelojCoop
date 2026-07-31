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


def _anular_franco_cerrado(conn, legajo, nombre, dias, anulado_en, periodo_origen_id=None):
    conn.execute("""
        INSERT INTO francos_anulaciones_cerrados
          (francos_tomados_id, legajo, nombre, departamento, tipo, fecha_desde, fecha_hasta,
           fechas_sueltas, dias, motivo, usuario, anulado_en, periodo_origen_id, periodo_aplicado_id)
        VALUES (0,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
    """, (legajo, nombre, "redes", "UNICO", "2026-06-15", "2026-06-15", "[]", dias,
          "test devolucion", "test", anulado_en, periodo_origen_id))
    conn.commit()


def test_devolucion_de_franco_anulado_no_se_reporta_como_diferencia(db_temporal):
    """Reproduce el caso real (Labanca/143, Barrientos/145): el cierre 1
    genera 3 (saldo_anterior=5 -> deja 8), pero entre el cierre 1 y el 2 se
    anula un franco que ya estaba 'Cerrado' y se devuelven 5 días
    directamente a francos_saldo_inicial.saldo (_devolver_saldo_franco_anulado,
    fuera del ciclo de cierre) -> el cierre 2 declara correctamente 13
    (8+5), no 8. Sin la devolución, esto se vería como una cadena rota de
    +5 -- la auditoría no debe reportarlo como diferencia."""
    conn = _conn(db_temporal)
    pid1 = _crear_cierre(
        conn, "2026-06-01 10:00:00", {"30": {"saldo": 5, "gen_extra_al_corte": 0}},
        [("30", "Empleado Devolucion", "redes", 3, 0)]
    )
    # Devolución ocurre DESPUES del cierre 1 y ANTES del cierre 2.
    _anular_franco_cerrado(conn, "30", "Empleado Devolucion", 5, "2026-06-15 09:00:00", pid1)
    _crear_cierre(
        conn, "2026-07-01 10:00:00", {"30": {"saldo": 13, "gen_extra_al_corte": 0}},  # 8 + 5 devueltos
        [("30", "Empleado Devolucion", "redes", 2, 0)]
    )
    _set_saldo_inicial(conn, "30", "Empleado Devolucion", 15)  # 13 + 2 generados en cierre 2
    conn.close()

    conn = _conn(db_temporal)
    resultados, con_diferencia, no_aplicables = servidor._auditoria_completa_saldos_francos(conn)
    conn.close()

    fila = next(r for r in resultados if r["legajo"] == "30")
    assert fila["saldo_recalculado_completo"] == 15
    assert fila["diferencia"] == 0
    assert not any(r["legajo"] == "30" for r in con_diferencia)


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


def test_verificar_cadena_pareada_tampoco_reporta_devolucion_como_desajuste(db_temporal, client):
    """El chequeo pareado original (/admin/verificar-cadena-saldos-francos)
    debe tener el mismo fix: una devolucion legitima entre dos cierres no
    debe aparecer en 'desajustes'."""
    conn = _conn(db_temporal)
    pid1 = _crear_cierre(
        conn, "2026-06-01 10:00:00", {"30": {"saldo": 5, "gen_extra_al_corte": 0}},
        [("30", "Empleado Devolucion", "redes", 3, 0)]
    )
    _anular_franco_cerrado(conn, "30", "Empleado Devolucion", 5, "2026-06-15 09:00:00", pid1)
    _crear_cierre(
        conn, "2026-07-01 10:00:00", {"30": {"saldo": 13, "gen_extra_al_corte": 0}},
        [("30", "Empleado Devolucion", "redes", 2, 0)]
    )
    conn.close()

    resp = client.get("/admin/verificar-cadena-saldos-francos")
    data = resp.get_json()
    assert data["cadena_sana"] is True
    assert data["desajustes"] == []


def test_revertir_y_recorregir_incidente_julio2026(db_temporal, client, monkeypatch):
    """Reproduce el incidente completo: 100/101 (Ingenieros) quedaron con un
    saldo incorrecto por una corrección vieja, y 143-estilo (legajo "30" acá,
    con devolución) también quedó mal por no considerar la devolución. La
    ruta de una sola vez debe revertir ambos casos en un solo llamado."""
    monkeypatch.setattr(servidor, "_REVERTIR_INGENIEROS_JUL2026", {"100": 5})

    conn = _conn(db_temporal)
    # Legajo 100: saldo incorrecto (simula la correccion erronea sobre
    # Ingenieros), sin ningun cierre de periodos relacionado necesario para
    # esta reversion puntual (se revierte por valor fijo, no por cadena).
    conn.execute(
        "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, nota, cargado_en, "
        "tomados_al_corte, gen_extra_al_corte, fecha_corte) VALUES (?,?,?,?,?,?,?,?)",
        ("100", "Mancioni Martin", 6, "correccion erronea", "2026-07-31 12:00:11", 0, 0, "2026-01-01"),
    )

    # Legajo "30": cadena con devolucion (como 143/145), pero el saldo en
    # vivo quedo en el valor MAL recalculado (sin la devolucion) por la
    # version vieja del codigo -- la re-correccion debe arreglarlo solo.
    pid1 = _crear_cierre(
        conn, "2026-06-01 10:00:00", {"30": {"saldo": 5, "gen_extra_al_corte": 0}},
        [("30", "Empleado Devolucion", "redes", 3, 0)]
    )
    _anular_franco_cerrado(conn, "30", "Empleado Devolucion", 5, "2026-06-15 09:00:00", pid1)
    _crear_cierre(
        conn, "2026-07-01 10:00:00", {"30": {"saldo": 13, "gen_extra_al_corte": 0}},
        [("30", "Empleado Devolucion", "redes", 2, 0)]
    )
    _set_saldo_inicial(conn, "30", "Empleado Devolucion", 10)  # mal: sin la devolucion (13+2=15 seria lo correcto)
    conn.close()

    resp = client.get("/admin/revertir-y-recorregir-cadena-saldos-julio2026?confirmar=si")
    data = resp.get_json()
    assert data["aplicado"] is True
    assert "backup" in data

    conn = _conn(db_temporal)
    saldo_100 = conn.execute(
        "SELECT saldo FROM francos_saldo_inicial WHERE legajo='100'"
    ).fetchone()["saldo"]
    saldo_30 = conn.execute(
        "SELECT saldo FROM francos_saldo_inicial WHERE legajo='30'"
    ).fetchone()["saldo"]
    conn.close()

    assert saldo_100 == 5, "debe revertirse al valor correcto conocido"
    assert saldo_30 == 15, "debe recalcularse solo con la devolucion incluida (13+2)"


# ── fecha_corte atrasada (incidente real del 31/07/2026: Generados duplicado) ──

def test_sincronizar_fecha_corte_detecta_y_corrige_atraso(db_temporal, client):
    """Reproduce el incidente: fecha_corte quedo en el cierre viejo (#2) en
    vez de avanzar al ultimo cierre activo (#4) -- por eso _calcular_saldos
    volvia a contar el cierre #4 como "Generados" aunque ya estaba absorbido
    en el saldo."""
    conn = _conn(db_temporal)
    _crear_cierre(conn, "2026-06-08 10:17:49", {"40": {"saldo": 5, "gen_extra_al_corte": 0}},
                  [("40", "Empleado Corte Atrasado", "redes", 3, 0)])
    _crear_cierre(conn, "2026-07-03 15:18:04", {"40": {"saldo": 8, "gen_extra_al_corte": 0}},
                  [("40", "Empleado Corte Atrasado", "redes", 2, 0)])
    # fecha_corte quedo mal: apunta al cierre viejo, no al ultimo (#4)
    conn.execute(
        "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, nota, cargado_en, "
        "tomados_al_corte, gen_extra_al_corte, fecha_corte) VALUES (?,?,?,?,?,?,?,?)",
        ("40", "Empleado Corte Atrasado", 10, "test", "2026-07-03 15:18:04",
         0, 0, "2026-06-08 10:17:49"),
    )
    conn.commit()
    conn.close()

    # Diagnostico puro
    conn = _conn(db_temporal)
    diag = servidor._fecha_corte_correcta_legajo(conn, "40")
    conn.close()
    assert diag["desactualizado"] is True
    assert diag["fecha_corte_correcta"] == "2026-07-03 15:18:04"

    # Dry-run no escribe
    resp = client.get("/admin/sincronizar-fecha-corte-saldos")
    data = resp.get_json()
    assert data["aplicado"] is False
    assert data["total_desactualizados"] == 1

    conn = _conn(db_temporal)
    corte_sin_confirmar = conn.execute(
        "SELECT fecha_corte FROM francos_saldo_inicial WHERE legajo='40'"
    ).fetchone()["fecha_corte"]
    conn.close()
    assert corte_sin_confirmar == "2026-06-08 10:17:49", "dry-run no debe escribir"

    # Confirmado: corrige y deja historial
    resp = client.get("/admin/sincronizar-fecha-corte-saldos?confirmar=si")
    data = resp.get_json()
    assert data["aplicado"] is True
    assert "backup" in data

    conn = _conn(db_temporal)
    fila = conn.execute(
        "SELECT saldo, fecha_corte FROM francos_saldo_inicial WHERE legajo='40'"
    ).fetchone()
    historial = conn.execute(
        "SELECT * FROM francos_fecha_corte_historial WHERE legajo='40'"
    ).fetchall()
    conn.close()

    assert fila["fecha_corte"] == "2026-07-03 15:18:04"
    assert fila["saldo"] == 10, "no debe tocar el saldo, solo fecha_corte"
    assert len(historial) == 1
    assert historial[0]["fecha_corte_anterior"] == "2026-06-08 10:17:49"
    assert historial[0]["fecha_corte_nueva"] == "2026-07-03 15:18:04"


def test_corregir_fecha_corte_no_regresa_corte_mas_reciente(db_temporal, client):
    """Reproduce la causa raiz del incidente: /admin/corregir-fecha-corte/<pid>
    (pensada para un solo cierre puntual) no debe pisar con una fecha VIEJA
    el corte de un legajo que ya avanzo a un cierre mas reciente."""
    conn = _conn(db_temporal)
    pid_viejo = _crear_cierre(
        conn, "2026-06-08 10:17:49", {"40": {"saldo": 5, "gen_extra_al_corte": 0}},
        [("40", "Empleado Ok", "redes", 3, 0)]
    )
    _crear_cierre(conn, "2026-07-03 15:18:04", {"40": {"saldo": 8, "gen_extra_al_corte": 0}},
                  [("40", "Empleado Ok", "redes", 2, 0)])
    # fecha_corte YA esta bien, apuntando al cierre mas reciente (#4)
    conn.execute(
        "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, nota, cargado_en, "
        "tomados_al_corte, gen_extra_al_corte, fecha_corte) VALUES (?,?,?,?,?,?,?,?)",
        ("40", "Empleado Ok", 10, "test", "2026-07-03 15:18:04", 0, 0, "2026-07-03 15:18:04"),
    )
    conn.commit()
    conn.close()

    # Alguien corre /admin/corregir-fecha-corte sobre el cierre VIEJO (#2) --
    # antes del fix, esto atrasaba fecha_corte al valor de ese cierre viejo.
    resp = client.post(f"/admin/corregir-fecha-corte/{pid_viejo}?confirmar=si")
    data = resp.get_json()
    assert data["ok"] is True
    assert "40" in data["diagnostico"]["omitidos_por_tener_corte_mas_reciente"]
    assert not any(c["legajo"] == "40" for c in data["diagnostico"]["cambios"])

    conn = _conn(db_temporal)
    fecha_corte_final = conn.execute(
        "SELECT fecha_corte FROM francos_saldo_inicial WHERE legajo='40'"
    ).fetchone()["fecha_corte"]
    conn.close()
    assert fecha_corte_final == "2026-07-03 15:18:04", "no debe atrasarse al cierre viejo"
