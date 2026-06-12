# -*- coding: utf-8 -*-
"""
/periodos/francos_pdf/<pid> — "Ver francos" del cierre.

El PDF debe:
- Leer el detalle de francos desde el SNAPSHOT del cierre
  (francos_cierre_detalle), nunca recalcular desde francos_tomados vivos
  (esos pueden cambiar después del cierre).
- Mostrar en el encabezado la fecha REAL del cierre (periodos.cerrado_en,
  formateada DD/MM/YYYY) como "Cargados hasta el", nunca la fecha actual.
- Mostrar la fecha actual solo como "Reimpreso el", nunca como fecha de cierre.
- Servirse inline (sin forzar descarga).
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


def _crear_periodo(conn, cerrado_en, departamento, legajo, nombre,
                    fecha_desde="2026-01-01", fecha_hasta="2026-01-07"):
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
        (cerrado_en, 1, 1, "periodo_test.json", fecha_desde, fecha_hasta, "ACTIVO"),
    )
    pid = cur.lastrowid
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
        "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, legajo, nombre, departamento, "0h", "0h", 0, 0, 0, "[]", 0),
    )
    conn.commit()
    return pid


def _insert_detalle(conn, pid, legajo, nombre, departamento, fecha_desde, dias=1):
    conn.execute("""
        INSERT INTO francos_cierre_detalle
          (periodo_id, legajo, nombre, departamento, tipo, fecha_desde, fecha_hasta,
           fechas_sueltas, dias, estado, fecha_emision, autorizado_por, observaciones)
        VALUES (?,?,?,?, 'UNICO', ?, ?, '[]', ?, 'Cerrado', '', '', '')
    """, (pid, legajo, nombre, departamento, fecha_desde, fecha_desde, dias))
    conn.commit()


def _insert_franco_vivo(conn, legajo, nombre, fecha_desde, cargado_en, estado="Aprobado"):
    conn.execute("""
        INSERT INTO francos_tomados
          (legajo, nombre, tipo, fecha_desde, fecha_hasta, fechas_sueltas, dias, estado, cargado_en)
        VALUES (?,?, 'UNICO', ?, ?, '[]', 1, ?, ?)
    """, (legajo, nombre, fecha_desde, fecha_desde, estado, cargado_en))
    conn.commit()


def _texto_pdf(pdf_bytes):
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_404_si_cierre_no_existe(db_temporal, client):
    resp = client.get("/periodos/francos_pdf/999")
    assert resp.status_code == 404


def test_pdf_lee_snapshot_no_datos_vivos(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"
    pid = _crear_periodo(conn, "2026-05-01T12:00:00.000000", "Redes", leg, nombre)
    _insert_detalle(conn, pid, leg, nombre, "Redes", "2026-04-15", dias=1)

    # Franco cargado DESPUÉS del cierre: vivo en francos_tomados, pero no
    # forma parte del snapshot de este cierre.
    _insert_franco_vivo(conn, leg, nombre, "2026-05-20", cargado_en="2026-05-15 10:00:00")

    resp = client.get(f"/periodos/francos_pdf/{pid}")
    assert resp.status_code == 200
    texto = _texto_pdf(resp.data)
    assert "2026-04-15" in texto
    assert "2026-05-20" not in texto


def test_header_muestra_fecha_real_de_cierre_y_reimpreso(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"
    pid = _crear_periodo(conn, "2026-05-01T12:00:00.000000", "Redes", leg, nombre)
    _insert_detalle(conn, pid, leg, nombre, "Redes", "2026-04-15", dias=1)

    resp = client.get(f"/periodos/francos_pdf/{pid}")
    texto = _texto_pdf(resp.data)

    assert "Cargados hasta el 01/05/2026" in texto
    hoy_fmt = datetime.now().strftime("%d/%m/%Y")
    assert f"Reimpreso el {hoy_fmt}" in texto
    # La fecha de hoy nunca debe figurar como "Cargados hasta"
    assert f"Cargados hasta el {hoy_fmt}" not in texto


def test_respuesta_inline_no_fuerza_descarga(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"
    pid = _crear_periodo(conn, "2026-05-01T12:00:00.000000", "Redes", leg, nombre)
    _insert_detalle(conn, pid, leg, nombre, "Redes", "2026-04-15", dias=1)

    resp = client.get(f"/periodos/francos_pdf/{pid}")
    assert resp.status_code == 200
    disposition = resp.headers.get("Content-Disposition", "")
    assert "attachment" not in disposition.lower()


def test_snapshot_vacio_genera_pdf_sin_filas(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"
    pid = _crear_periodo(conn, "2026-05-01T12:00:00.000000", "Redes", leg, nombre)
    # Sin filas en francos_cierre_detalle para este cierre.

    resp = client.get(f"/periodos/francos_pdf/{pid}")
    assert resp.status_code == 200
    texto = _texto_pdf(resp.data)
    assert "Cargados hasta el 01/05/2026" in texto
    assert "TOTAL" in texto
