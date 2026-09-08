# -*- coding: utf-8 -*-
"""
Pantalla de administración para agregar/quitar legajos de
recursos/excluidos_ot.json (/configuracion/excluidos-ot/nuevo y
/configuracion/excluidos-ot/eliminar/<legajo>).

Aisla el archivo real con monkeypatch.chdir a un directorio temporal --
_cargar_excluidos_ot_detalle/_guardar_excluidos_ot_detalle usan una ruta
relativa ("recursos/excluidos_ot.json"), igual que la ya existente
_cargar_excluidos_ot(), así que nunca deben tocar el archivo real del
proyecto durante los tests.
"""
import json
from pathlib import Path

import pytest

import servidor


@pytest.fixture
def recursos_temporales(tmp_path, monkeypatch):
    (tmp_path / "recursos").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path / "recursos" / "excluidos_ot.json"


@pytest.fixture(autouse=True)
def _patch_io(monkeypatch):
    monkeypatch.setattr(servidor, "_autenticado", lambda: True)


@pytest.fixture
def client():
    servidor.app.config["TESTING"] = True
    with servidor.app.test_client() as c:
        yield c


def _escribir_json(ruta, legajos, nombres):
    ruta.write_text(json.dumps({"legajos": legajos, "nombres": nombres}), encoding="utf-8")


def test_agregar_legajo_nuevo(client, recursos_temporales):
    _escribir_json(recursos_temporales, ["3"], ["Urrutia Silvia"])

    res = client.post("/configuracion/excluidos-ot/nuevo",
                       data={"legajo": "127", "nombre": "Rohr"})
    assert res.status_code == 302
    assert "ok=excluido" in res.headers["Location"]

    data = json.loads(recursos_temporales.read_text(encoding="utf-8"))
    assert data["legajos"] == ["3", "127"]
    assert data["nombres"] == ["Urrutia Silvia", "Rohr"]


def test_agregar_legajo_duplicado_da_error_y_no_modifica_nada(client, recursos_temporales):
    _escribir_json(recursos_temporales, ["120"], ["Barrientos Roberto"])

    res = client.post("/configuracion/excluidos-ot/nuevo",
                       data={"legajo": "120", "nombre": "Otro nombre"})
    assert "error=excl_ya_existe" in res.headers["Location"]

    data = json.loads(recursos_temporales.read_text(encoding="utf-8"))
    assert data == {"legajos": ["120"], "nombres": ["Barrientos Roberto"]}


def test_agregar_sin_legajo_da_error(client, recursos_temporales):
    _escribir_json(recursos_temporales, [], [])
    res = client.post("/configuracion/excluidos-ot/nuevo", data={"nombre": "Sin legajo"})
    assert "error=excl_legajo_requerido" in res.headers["Location"]


def test_agregar_completa_nombre_desde_empleados_conocidos(client, recursos_temporales, monkeypatch):
    _escribir_json(recursos_temporales, [], [])
    monkeypatch.setattr(
        servidor, "_empleados_conocidos",
        lambda: [{"legajo": "55", "nombre": "PEREZ ANA"}],
    )
    client.post("/configuracion/excluidos-ot/nuevo", data={"legajo": "55"})
    data = json.loads(recursos_temporales.read_text(encoding="utf-8"))
    assert data == {"legajos": ["55"], "nombres": ["PEREZ ANA"]}


def test_eliminar_legajo(client, recursos_temporales):
    _escribir_json(recursos_temporales, ["3", "120", "127"],
                    ["Urrutia Silvia", "Barrientos Roberto", "Rohr"])

    res = client.post("/configuracion/excluidos-ot/eliminar/120")
    assert "ok=excl_eliminado" in res.headers["Location"]

    data = json.loads(recursos_temporales.read_text(encoding="utf-8"))
    assert data["legajos"] == ["3", "127"]
    assert data["nombres"] == ["Urrutia Silvia", "Rohr"]


def test_eliminar_legajo_inexistente_no_rompe(client, recursos_temporales):
    _escribir_json(recursos_temporales, ["3"], ["Urrutia Silvia"])
    res = client.post("/configuracion/excluidos-ot/eliminar/999")
    assert res.status_code == 302
    data = json.loads(recursos_temporales.read_text(encoding="utf-8"))
    assert data["legajos"] == ["3"]


def test_agregar_y_eliminar_se_reflejan_en_cargar_excluidos_ot(client, recursos_temporales):
    """El set que usan los informes de cierre (_cargar_excluidos_ot) debe
    reflejar los cambios hechos desde la pantalla nueva."""
    _escribir_json(recursos_temporales, [], [])
    client.post("/configuracion/excluidos-ot/nuevo", data={"legajo": "200", "nombre": "Nuevo"})
    assert servidor._cargar_excluidos_ot() == {"200"}
    client.post("/configuracion/excluidos-ot/eliminar/200")
    assert servidor._cargar_excluidos_ot() == set()
