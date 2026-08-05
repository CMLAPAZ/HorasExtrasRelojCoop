# -*- coding: utf-8 -*-
"""
/historial -- "Todas" (semana vacía) dejó de mostrar el archivo completo
(mezclaba meses ya cerrados con el período activo, causando confusión real
a la usuaria el 04/08/2026: "por que me muestra las semanas de Junio!!!!").
Ahora "Todas" muestra solo las semanas del período ACTIVO (las mismas que
aparecen en Períodos); para ver el archivo completo hay que elegir
explícitamente esa opción, y una semana vieja puntual se sigue pudiendo
elegir por número.
"""
import json

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


def _confirmacion(servidor_mod, nombre_archivo, legajo, nombre, semana, fecha, franco=0):
    servidor_mod.CONFIRM_DIR.mkdir(exist_ok=True, parents=True)
    (servidor_mod.CONFIRM_DIR / nombre_archivo).write_text(json.dumps({
        "legajo": legajo, "nombre": nombre, "departamento": "Redes", "semana": semana,
        "confirmado_en": f"{fecha}T10:00:00",
        "dias": [{"fecha": fecha, "franco": franco, "ot50": "00:00:00",
                   "ot100": "00:00:00", "comida": 0, "tiene_ot": bool(franco)}],
        "totales": {"ot50": "0h", "ot100": "0h", "comidas": 0, "francos": franco, "tardanzas": 0},
    }, ensure_ascii=False), encoding="utf-8")


def test_historial_todas_muestra_solo_periodo_activo_no_meses_cerrados(db_temporal, client):
    leg, nombre = "121", "CASTRILLON DIEGO"

    # Semana vieja (junio), ya cerrada -- no está en metadata activa.
    _confirmacion(servidor, "vieja_junio.json", leg, nombre, semana=3, fecha="2026-06-13", franco=1)
    # Semana del período activo (julio) -- sí está en metadata.
    _confirmacion(servidor, "activa_julio.json", leg, nombre, semana=99, fecha="2026-07-18", franco=1)

    servidor._guardar_metadata({
        "semana_actual": 99,
        "semanas": [{
            # num_depto distinto de la "semana":3 de la confirmación vieja
            # a propósito, para no confundir dos conceptos que coinciden
            # solo por casualidad en este test.
            "numero": 99, "num_depto": 5, "departamento": "Redes",
            "fecha_desde": "2026-07-13", "fecha_hasta": "2026-07-19",
            "archivo": "semana_99.csv",
        }],
    })

    resp_default = client.get("/historial?departamento=redes")
    assert resp_default.status_code == 200
    body = resp_default.get_data(as_text=True)
    assert "2026-07-18" in body
    assert "2026-06-13" not in body

    resp_archivo = client.get("/historial?departamento=redes&semana=archivo_completo")
    assert resp_archivo.status_code == 200
    body_archivo = resp_archivo.get_data(as_text=True)
    assert "2026-07-18" in body_archivo
    assert "2026-06-13" in body_archivo

    resp_semana_vieja = client.get("/historial?departamento=redes&semana=3")
    assert resp_semana_vieja.status_code == 200
    body_vieja = resp_semana_vieja.get_data(as_text=True)
    assert "2026-06-13" in body_vieja
    assert "2026-07-18" not in body_vieja
