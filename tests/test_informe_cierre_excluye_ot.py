# -*- coding: utf-8 -*-
"""
_generar_pdf_cierre_completo (el "informe completo" que se descarga desde
/periodos/<pid>/informe_completo) no debe sumar al total del departamento
las horas de los legajos marcados en recursos/excluidos_ot.json (categoria
distinta, horas de control que no se liquidan) -- ni en la seccion "Detalle
de horas dia a dia" ni en "Resumen de totales del periodo".

Usa el archivo REAL recursos/excluidos_ot.json (no se mockea) porque ya
tiene cargados los legajos reales del pedido: 3-Urrutia Silvia,
120-Barrientos Roberto, 127-Rohr.
"""
import sqlite3

import pandas as pd
import pytest
from pypdf import PdfReader
from io import BytesIO

import servidor


@pytest.fixture
def db_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(servidor, "DATOS_DIR", tmp_path)
    monkeypatch.setattr(servidor, "DB_FILE", tmp_path / "cierres_test.db")
    monkeypatch.setattr(servidor, "SEMANAS_DIR", tmp_path / "semanas")
    monkeypatch.setattr(servidor, "PERIODOS_DIR", tmp_path / "periodos")
    servidor._init_db()
    return servidor.DB_FILE


def _conn(db_file):
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    return conn


def _texto_pdf(pdf_bytes):
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_informe_cierre_no_suma_horas_de_legajo_excluido(db_temporal):
    # Legajo 120 (BARRIENTOS ROBERTO) ya está en recursos/excluidos_ot.json.
    LEG_EXCLUIDO = "120"
    LEG_NORMAL = "998"

    # ── Semana con fichadas reales de ambos legajos (Redes, mismo día) ──
    filas = []
    for leg, nombre, salida in [
        (LEG_NORMAL, "EMPLEADO NORMAL", "15:00:00"),   # 9h -> 2h al 50%
        (LEG_EXCLUIDO, "BARRIENTOS ROBERTO", "20:00:00"),  # 14h -> 7h al 50%
    ]:
        filas.append({"Legajo": leg, "Nombre": nombre, "Departamento": "Redes",
                       "FechaHora": "2026-01-05 06:00:00", "Tipo": "ENTRADA"})
        filas.append({"Legajo": leg, "Nombre": nombre, "Departamento": "Redes",
                       "FechaHora": f"2026-01-05 {salida}", "Tipo": "SALIDA"})
    df = pd.DataFrame(filas)
    servidor._guardar_semana_csv(1, df)

    # ── Cierre en periodo_empleados (lo que lee la sección "Resumen de totales") ──
    with _conn(db_temporal) as conn:
        cur = conn.execute(
            "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
            "fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
            ("2026-01-09T12:00:00", 1, 1, "no_existe.json",
             "2026-01-05", "2026-01-11", "ACTIVO"),
        )
        pid = cur.lastrowid
        conn.execute(
            "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
            "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, LEG_NORMAL, "EMPLEADO NORMAL", "Redes", "2h", "0h", 1, 0, 0, "[1]", 1),
        )
        conn.execute(
            "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
            "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, LEG_EXCLUIDO, "BARRIENTOS ROBERTO", "Redes", "7h", "0h", 2, 0, 0, "[1]", 1),
        )
        conn.commit()

    pdf_bytes = servidor._generar_pdf_cierre_completo(pid)
    texto = _texto_pdf(pdf_bytes)

    # Las horas del excluido deben seguir viéndose en su propia fila/página
    # (es información de control, solo no se suma al total).
    assert "BARRIENTOS ROBERTO" in texto
    assert "07:00:00" in texto or "7h" in texto  # su propio 50% en algún lado del PDF

    # El total sumado (bug) daría 9h de 50% (2h normal + 7h excluido); no debe aparecer
    # ni en la sección de detalle ni en el resumen.
    assert "09:00:00" not in texto
    assert "9h" not in texto

    # El total correcto (solo el legajo normal) sí debe aparecer.
    assert "02:00:00" in texto


def test_informe_cierre_incluye_horas_de_legajo_normal(db_temporal):
    """Control negativo: un legajo SIN excluir sí debe sumarse (para no
    terminar con un filtro que excluye a todo el mundo por error)."""
    LEG_NORMAL = "997"
    df = pd.DataFrame([
        {"Legajo": LEG_NORMAL, "Nombre": "OTRO NORMAL", "Departamento": "Redes",
         "FechaHora": "2026-01-05 06:00:00", "Tipo": "ENTRADA"},
        {"Legajo": LEG_NORMAL, "Nombre": "OTRO NORMAL", "Departamento": "Redes",
         "FechaHora": "2026-01-05 15:00:00", "Tipo": "SALIDA"},
    ])
    servidor._guardar_semana_csv(1, df)

    with _conn(db_temporal) as conn:
        cur = conn.execute(
            "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
            "fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
            ("2026-01-09T12:00:00", 1, 1, "no_existe.json",
             "2026-01-05", "2026-01-11", "ACTIVO"),
        )
        pid = cur.lastrowid
        conn.execute(
            "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
            "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, LEG_NORMAL, "OTRO NORMAL", "Redes", "2h", "0h", 1, 0, 0, "[1]", 1),
        )
        conn.commit()

    pdf_bytes = servidor._generar_pdf_cierre_completo(pid)
    texto = _texto_pdf(pdf_bytes)
    assert "02:00:00" in texto
