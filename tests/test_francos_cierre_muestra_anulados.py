# -*- coding: utf-8 -*-
"""
francos_cierre_detalle es un snapshot inmutable de como estaba el franco
AL MOMENTO del cierre -- si el franco se anula despues (via
/francos/anular-cerrado), esa fila seguia mostrando "Aprobado" para
siempre en el detalle de francos de ese cierre (PDF "Ver francos", informe
completo del cierre, informe mensual combinado), aunque el saldo ya se
hubiera corregido por separado via _devolver_saldo_franco_anulado.

Reportado por la usuaria el 08/09/2026: anulo un franco de Barrientos
Rodrigo (151) que ya estaba en el cierre #9 de Redes, y seguia figurando
"Aprobado" en el detalle de francos tomados.

Fix: _anulados_por_franco_id() + _estado_obs_franco_cierre() cruzan
francos_cierre_detalle.francos_tomados_id contra
francos_anulaciones_cerrados (sin importar a que cierre se le aplico la
devolucion del dia) y muestran "Anulado" + fecha/motivo en vez del
"Aprobado" congelado.
"""
import sqlite3
from datetime import datetime
from io import BytesIO

import pytest
from pypdf import PdfReader

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


def _texto_pdf(pdf_bytes):
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# ─── Unit tests de los helpers ──────────────────────────────────────────

def test_anulados_por_franco_id_ignora_ids_vacios():
    # Con ids falsy (None/0/'') no debe ni tocar la conexión -- se puede
    # pasar None sin romper.
    assert servidor._anulados_por_franco_id(None, [None, 0, ""]) == {}


def test_estado_obs_franco_cierre_sin_anulacion():
    ft = {"francos_tomados_id": 50, "estado": "Aprobado", "observaciones": "obs original"}
    estado, obs, fue_anulado = servidor._estado_obs_franco_cierre(ft, {})
    assert estado == "Aprobado"
    assert obs == "obs original"
    assert fue_anulado is False


def test_estado_obs_franco_cierre_con_anulacion():
    # Obs. compacta a propósito -- una de las 3 columnas donde se muestra
    # (PDF "Ver francos") es angosta y no entra "Anulado el YYYY-MM-DD —
    # motivo largo". "Anulado" ya se ve en Estado; acá solo la fecha corta.
    ft = {"francos_tomados_id": 50, "estado": "Aprobado", "observaciones": ""}
    anulados = {50: {"anulado_en": "2026-09-08 10:00:00", "motivo": "cargado por error"}}
    estado, obs, fue_anulado = servidor._estado_obs_franco_cierre(ft, anulados)
    assert estado == "Anulado"
    assert obs == "Anul. 08/09/2026"
    assert fue_anulado is True


# ─── Integración: PDF "Ver francos" del cierre ──────────────────────────

def test_pdf_ver_francos_muestra_anulado_en_vez_de_aprobado(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "151", "BARRIENTOS RODRIGO"
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
        ("2026-09-08T12:39:00", 1, 4, "periodo_test.json",
         "2026-08-03", "2026-08-30", "ACTIVO"),
    )
    pid = cur.lastrowid

    # El franco original en francos_tomados (para que exista el id real)
    cur2 = conn.execute(
        "INSERT INTO francos_tomados (legajo, nombre, tipo, fecha_desde, fecha_hasta, "
        "fechas_sueltas, dias, estado, cargado_en) VALUES (?,?,?,?,?,?,?,?,?)",
        (leg, nombre, "UNICO", "2026-08-21", "2026-08-21", "[]", 1, "Cerrado", "2026-08-10 09:00:00"),
    )
    ft_id = cur2.lastrowid

    # El snapshot del cierre, apuntando a ese mismo id.
    conn.execute(
        "INSERT INTO francos_cierre_detalle (periodo_id, legajo, nombre, departamento, tipo, "
        "fecha_desde, fecha_hasta, fechas_sueltas, dias, estado, fecha_emision, autorizado_por, "
        "observaciones, francos_tomados_id) VALUES (?,?,?,?, 'UNICO', ?, ?, '[]', ?, 'Aprobado', "
        "'', '', '', ?)",
        (pid, leg, nombre, "Redes", "2026-08-21", "2026-08-21", 1, ft_id),
    )

    # Otro franco normal, sin anular, del mismo cierre -- control negativo.
    conn.execute(
        "INSERT INTO francos_cierre_detalle (periodo_id, legajo, nombre, departamento, tipo, "
        "fecha_desde, fecha_hasta, fechas_sueltas, dias, estado, fecha_emision, autorizado_por, "
        "observaciones, francos_tomados_id) VALUES (?,?,?,?, 'UNICO', ?, ?, '[]', ?, 'Aprobado', "
        "'', '', '', NULL)",
        (pid, "120", "BARRIENTOS ROBERTO", "Redes", "2026-09-01", "2026-09-01", 1),
    )

    # La anulación, hecha DESPUÉS de cerrar #9 (simulado con fecha posterior).
    conn.execute(
        "INSERT INTO francos_anulaciones_cerrados (francos_tomados_id, legajo, nombre, "
        "departamento, tipo, fecha_desde, fecha_hasta, fechas_sueltas, dias, motivo, usuario, "
        "anulado_en, periodo_origen_id, periodo_aplicado_id, aplicado_en) VALUES "
        "(?,?,?,?, 'UNICO', ?, ?, '[]', ?, ?, ?, ?, ?, NULL, '')",
        (ft_id, leg, nombre, "Redes", "2026-08-21", "2026-08-21", 1,
         "cargado por error", "Carola", "2026-09-08 10:00:00", pid),
    )
    conn.commit()
    conn.close()

    resp = client.get(f"/periodos/francos_pdf/{pid}")
    assert resp.status_code == 200
    texto = _texto_pdf(resp.data)

    assert "BARRIENTOS RODRIGO" in texto
    assert "Anulado" in texto
    assert "08/09/2026" in texto  # fecha corta en Obs., formato DD/MM/YYYY
    # El otro franco (no anulado) debe seguir figurando como Aprobado.
    assert "BARRIENTOS ROBERTO" in texto


# ─── Integración: pantalla web /periodos/ver/<id> ───────────────────────

def test_periodos_ver_muestra_anulado_en_seccion_francos(db_temporal, client):
    """Mismo caso que el test anterior, pero para la pantalla web
    (periodo_detalle.html), no el PDF -- es una cuarta ubicación distinta
    que lee francos_cierre_detalle por su cuenta y tampoco cruzaba contra
    francos_anulaciones_cerrados."""
    conn = _conn(db_temporal)
    leg, nombre = "151", "BARRIENTOS RODRIGO"
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
        ("2026-09-08T12:39:00", 1, 4, "periodo_test.json",
         "2026-08-03", "2026-08-30", "ACTIVO"),
    )
    pid = cur.lastrowid

    cur2 = conn.execute(
        "INSERT INTO francos_tomados (legajo, nombre, tipo, fecha_desde, fecha_hasta, "
        "fechas_sueltas, dias, estado, cargado_en) VALUES (?,?,?,?,?,?,?,?,?)",
        (leg, nombre, "UNICO", "2026-08-21", "2026-08-21", "[]", 1, "Cerrado", "2026-08-10 09:00:00"),
    )
    ft_id = cur2.lastrowid

    conn.execute(
        "INSERT INTO francos_cierre_detalle (periodo_id, legajo, nombre, departamento, tipo, "
        "fecha_desde, fecha_hasta, fechas_sueltas, dias, estado, fecha_emision, autorizado_por, "
        "observaciones, francos_tomados_id) VALUES (?,?,?,?, 'UNICO', ?, ?, '[]', ?, 'Aprobado', "
        "'', '', '', ?)",
        (pid, leg, nombre, "Redes", "2026-08-21", "2026-08-21", 1, ft_id),
    )
    conn.execute(
        "INSERT INTO francos_anulaciones_cerrados (francos_tomados_id, legajo, nombre, "
        "departamento, tipo, fecha_desde, fecha_hasta, fechas_sueltas, dias, motivo, usuario, "
        "anulado_en, periodo_origen_id, periodo_aplicado_id, aplicado_en) VALUES "
        "(?,?,?,?, 'UNICO', ?, ?, '[]', ?, ?, ?, ?, ?, NULL, '')",
        (ft_id, leg, nombre, "Redes", "2026-08-21", "2026-08-21", 1,
         "cargado por error", "Carola", "2026-09-08 10:00:00", pid),
    )
    conn.commit()
    conn.close()

    resp = client.get(f"/periodos/ver/{pid}")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)

    assert 'class="badge-anulado"' in texto
    assert "Anul. 08/09/2026" in texto
    # No debe seguir mostrando el badge verde de "Aprobado" para esa fila.
    idx_badge_anulado = texto.index('class="badge-anulado"')
    idx_barrientos = texto.index("BARRIENTOS RODRIGO")
    assert abs(idx_badge_anulado - idx_barrientos) < 500
