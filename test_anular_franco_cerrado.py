# -*- coding: utf-8 -*-
"""
Tests de /francos/anular-cerrado/<fid>: anular y devolver un franco ya
'Cerrado' sin modificar el cierre histórico donde figuraba.
"""
import json
from datetime import datetime

import pytest

import servidor


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(servidor, "DB_FILE", tmp_path / "test_cierres.db")
    servidor._init_db()
    servidor.app.config["TESTING"] = True
    with servidor.app.test_client() as c:
        with c.session_transaction() as sess:
            sess["auth"] = True
        yield c


def _crear_franco_cerrado(legajo="143", nombre="LABANCA JOEL",
                           fecha_desde="2026-07-13", fecha_hasta="2026-07-17", dias=4):
    """Inserta un franco ya 'Cerrado' + su copia inmutable en
    francos_cierre_detalle, simulando un cierre histórico real (periodo #1)."""
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with servidor._get_db() as conn:
        conn.execute(
            "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, fecha_desde, fecha_hasta, estado) "
            "VALUES (?,1,1,'periodo_test.json',?,?, 'ACTIVO')",
            (ahora, fecha_desde, fecha_hasta)
        )
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO francos_tomados (legajo, nombre, tipo, fecha_desde, fecha_hasta, dias, estado, cargado_en) "
            "VALUES (?,?,'RANGO',?,?,?, 'Cerrado', ?)",
            (legajo, nombre, fecha_desde, fecha_hasta, dias, ahora)
        )
        fid = cur.lastrowid
        conn.execute(
            "INSERT INTO francos_cierre_detalle (periodo_id, legajo, nombre, departamento, tipo, "
            "fecha_desde, fecha_hasta, dias, estado) VALUES (?,?,?,?,'RANGO',?,?,?, 'Cerrado')",
            (pid, legajo, nombre, "Administración", fecha_desde, fecha_hasta, dias)
        )
        conn.execute(
            "INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, tomados_al_corte, fecha_corte, cargado_en) "
            "VALUES (?,?,0,?,?,?)",
            (legajo, nombre, dias, "2099-01-01", ahora)  # fecha_corte futura => el franco cuenta como "ya al corte"
        )
        conn.commit()
    return pid, fid


def test_anular_devuelve_saldo(cliente):
    pid, fid = _crear_franco_cerrado()
    saldo_antes = next(s for s in servidor._calcular_saldos() if s["legajo"] == "143")["saldo_actual"]

    r = cliente.post(f"/francos/anular-cerrado/{fid}", data={"motivo": "carga duplicada", "usuario": "Carola"})
    assert r.status_code == 302

    saldo_despues = next(s for s in servidor._calcular_saldos() if s["legajo"] == "143")["saldo_actual"]
    assert saldo_despues == saldo_antes + 4


def test_anular_libera_fechas(cliente):
    pid, fid = _crear_franco_cerrado()
    with servidor._get_db() as conn:
        error_antes = servidor._validar_franco_nuevo(conn, "143", "UNICO", "2026-07-14", "2026-07-14", [])
    assert error_antes is not None  # bloqueado por francos_cierre_detalle

    cliente.post(f"/francos/anular-cerrado/{fid}", data={"motivo": "error de carga"})

    with servidor._get_db() as conn:
        error_despues = servidor._validar_franco_nuevo(conn, "143", "UNICO", "2026-07-14", "2026-07-14", [])
    assert error_despues is None


def test_no_modifica_cierre_historico(cliente):
    pid, fid = _crear_franco_cerrado()
    with servidor._get_db() as conn:
        antes = [dict(r) for r in conn.execute(
            "SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid,)
        ).fetchall()]

    cliente.post(f"/francos/anular-cerrado/{fid}", data={"motivo": "error de carga"})

    with servidor._get_db() as conn:
        despues = [dict(r) for r in conn.execute(
            "SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid,)
        ).fetchall()]
    assert antes == despues


def test_devolucion_aparece_en_proximo_cierre(cliente):
    pid, fid = _crear_franco_cerrado()
    cliente.post(f"/francos/anular-cerrado/{fid}", data={"motivo": "error de carga"})

    with servidor._get_db() as conn:
        conn.execute(
            "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, fecha_desde, fecha_hasta, estado) "
            "VALUES (?,2,2,'periodo_test2.json','2026-08-01','2026-08-07','ACTIVO')",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),)
        )
        pid2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        devoluciones = servidor._snapshot_francos_cierre(conn, pid2, "2026-08-08 00:00:00", legajos=["143"], departamento="Administración")
        conn.commit()

    assert len(devoluciones) == 1
    assert devoluciones[0]["dias"] == 4

    with servidor._get_db() as conn:
        row = conn.execute(
            "SELECT periodo_aplicado_id FROM francos_anulaciones_cerrados WHERE francos_tomados_id=?", (fid,)
        ).fetchone()
    assert row["periodo_aplicado_id"] == pid2


def test_no_permite_anular_sin_motivo(cliente):
    pid, fid = _crear_franco_cerrado()
    r = cliente.post(f"/francos/anular-cerrado/{fid}", data={"motivo": ""})
    assert "error=motivo_requerido" in r.headers["Location"]

    with servidor._get_db() as conn:
        estado = conn.execute("SELECT estado FROM francos_tomados WHERE id=?", (fid,)).fetchone()["estado"]
    assert estado == "Cerrado"


def test_no_permite_anular_dos_veces(cliente):
    pid, fid = _crear_franco_cerrado()
    r1 = cliente.post(f"/francos/anular-cerrado/{fid}", data={"motivo": "primera vez"})
    assert "ok=anulado_cerrado" in r1.headers["Location"]

    r2 = cliente.post(f"/francos/anular-cerrado/{fid}", data={"motivo": "segunda vez"})
    assert "error=franco_no_cerrado" in r2.headers["Location"]

    with servidor._get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as c FROM francos_anulaciones_cerrados WHERE francos_tomados_id=?", (fid,)
        ).fetchone()["c"]
    assert total == 1


def test_queda_registrada_la_auditoria(cliente):
    pid, fid = _crear_franco_cerrado()
    cliente.post(f"/francos/anular-cerrado/{fid}", data={"motivo": "ajuste solicitado por RRHH", "usuario": "Carola Martin"})

    with servidor._get_db() as conn:
        row = conn.execute(
            "SELECT motivo_anulacion, usuario_anulacion, fecha_anulacion FROM francos_tomados WHERE id=?", (fid,)
        ).fetchone()
        aud = conn.execute(
            "SELECT * FROM francos_anulaciones_cerrados WHERE francos_tomados_id=?", (fid,)
        ).fetchone()
    assert row["motivo_anulacion"] == "ajuste solicitado por RRHH"
    assert row["usuario_anulacion"] == "Carola Martin"
    assert row["fecha_anulacion"]
    assert aud["motivo"] == "ajuste solicitado por RRHH"
    assert aud["dias"] == 4


def test_requiere_autenticacion(tmp_path, monkeypatch):
    monkeypatch.setattr(servidor, "DB_FILE", tmp_path / "test_cierres2.db")
    servidor._init_db()
    pid, fid = _crear_franco_cerrado()

    with servidor.app.test_client() as c:
        r = c.post(f"/francos/anular-cerrado/{fid}", data={"motivo": "intento sin login"})
        assert r.status_code in (302, 401)
        if r.status_code == 302:
            assert "/login" in r.headers["Location"]

    with servidor._get_db() as conn:
        estado = conn.execute("SELECT estado FROM francos_tomados WHERE id=?", (fid,)).fetchone()["estado"]
    assert estado == "Cerrado"
