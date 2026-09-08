# -*- coding: utf-8 -*-
"""
/periodos/ver/<pid> (periodo_detalle.html) sumaba en el total del
departamento las horas de legajos con otra categoria (excluidos_ot.json,
ej. Barrientos Roberto-120) -- a diferencia de la pantalla de Periodos
activo (periodo.html) y del informe de cierre en PDF
(_generar_pdf_cierre_completo), que ya excluian correctamente esas horas
del total, esta pantalla nunca calculaba/adjuntaba excluido_ot por
empleado (periodo_empleados no tiene esa columna), asi que el JS del
template sumaba todo sin filtrar.

Reportado por la usuaria el 08/09/2026 comparando a mano el total de esta
pantalla contra el del PDF (que si daba bien).
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


def test_periodos_ver_marca_excluido_ot_por_legajo(db_temporal, client):
    conn = _conn(db_temporal)
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
        ("2026-09-08T12:39:00", 1, 4, "periodo_test.json",
         "2026-08-03", "2026-08-30", "ACTIVO"),
    )
    pid = cur.lastrowid
    # Barrientos Roberto (120) ya está en recursos/excluidos_ot.json (no se mockea).
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
        "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, "120", "BARRIENTOS ROBERTO", "Redes", "1h", "12h", 1, 2, 0, "[1,2,3,4]", 1),
    )
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
        "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, "121", "CASTRILLON DIEGO", "Redes", "0h", "5h", 0, 1, 0, "[1,2,3,4]", 1),
    )
    conn.commit()
    conn.close()

    resp = client.get(f"/periodos/ver/{pid}")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)

    # Extraer el array de empleados embebido como JSON en el <script>
    inicio = texto.index("const _emps = ") + len("const _emps = ")
    fin = texto.index(";", inicio)
    emps = json.loads(texto[inicio:fin])
    por_legajo = {e["legajo"]: e for e in emps}

    assert por_legajo["120"]["excluido_ot"] is True
    assert por_legajo["121"]["excluido_ot"] is False
