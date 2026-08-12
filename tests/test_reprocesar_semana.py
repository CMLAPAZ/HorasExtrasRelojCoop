# -*- coding: utf-8 -*-
"""
Regresión: reprocesar_semana() — hotfix 'del _sesion[leg_t] if ...'

Error original: SyntaxError (cannot delete conditional expression)
  del _sesion[leg_t] if leg_t in _sesion else None

Corrección aplicada:
  if leg_t in _sesion:
      del _sesion[leg_t]
"""
import io
from datetime import date

import pytest
import servidor


# ──────────────────────────────────────────────────────────────
# Datos ficticios
# ──────────────────────────────────────────────────────────────

_CSV_BYTES = (
    "Nro. de usuario,Nombre,Departamento,Fecha/Hora,Tipo de registro\n"
    "100,Juan,REDES,2025-09-01 06:00:00,ENTRADA\n"
    "100,Juan,REDES,2025-09-01 14:00:00,SALIDA\n"
).encode("utf-8")


def _sesion_dos_empleados():
    """_sesion con Juan (100) y Ana (200), token + clave legajo inversa."""
    return {
        "tok_100": {
            "legajo": "100", "nombre": "Juan", "departamento": "REDES",
            "semana": 1, "semana_depto": 1,
            "confirmado": False, "confirmado_en": None,
            "dias": [], "totales": {}, "excluido_ot": False,
        },
        "100": {"legajo": "100"},
        "tok_200": {
            "legajo": "200", "nombre": "Ana", "departamento": "REDES",
            "semana": 1, "semana_depto": 1,
            "confirmado": False, "confirmado_en": None,
            "dias": [], "totales": {}, "excluido_ot": False,
        },
        "200": {"legajo": "200"},
    }


def _meta(tokens=None):
    return {
        "semanas": [{
            "numero": 1,
            "num_depto": 1,
            "departamento": "REDES",
            "tokens": tokens if tokens is not None else ["tok_100", "tok_200"],
        }],
        "total": 1,
    }


def _emp_juan():
    return {"legajo": "100", "nombre": "Juan", "registros": [], "excluido_ot": False}


def _emp_ana():
    return {"legajo": "200", "nombre": "Ana", "registros": [], "excluido_ot": False}


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_io(monkeypatch, tmp_path):
    """Bloquea toda escritura en disco y parchea autenticación.

    SEMANAS_DIR apunta a un tmp_path -- sin esto, el branch solo_legajos
    de reprocesar_semana() lee semana_N.csv desde la carpeta real del
    proyecto (semanas/), no un archivo de prueba."""
    monkeypatch.setattr(servidor, "_autenticado", lambda: True)
    monkeypatch.setattr(servidor, "_guardar_sesion", lambda s: None)
    monkeypatch.setattr(servidor, "_guardar_metadata", lambda m: None)
    monkeypatch.setattr(servidor, "_guardar_semana_csv", lambda n, df: None)
    monkeypatch.setattr(servidor, "SEMANAS_DIR", tmp_path)
    monkeypatch.setattr(servidor, "_wa_url", lambda *a, **kw: "")


@pytest.fixture
def client():
    servidor.app.config["TESTING"] = True
    with servidor.app.test_client() as c:
        yield c


def _reprocesar(client, n, csv_bytes, solo_legajos=None):
    data = {"csv": (io.BytesIO(csv_bytes), "fichadas.csv")}
    if solo_legajos:
        data["solo_legajos"] = solo_legajos
    return client.post(
        f"/semanas/{n}/reprocesar",
        data=data,
        content_type="multipart/form-data",
    )


# ──────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────

def test_empleado_ausente_eliminado_de_sesion(monkeypatch, client):
    """
    Ana (200) desaparece del nuevo CSV.
    Su token y la clave legajo inversa deben eliminarse de _sesion.
    """
    sesion = _sesion_dos_empleados()
    monkeypatch.setattr(servidor, "_sesion", sesion)
    monkeypatch.setattr(servidor, "_cargar_metadata", lambda: _meta())
    monkeypatch.setattr(
        servidor, "_procesar_empleados",
        lambda df, deptos: ([_emp_juan()], date(2025, 9, 1), date(2025, 9, 7)),
    )

    resp = _reprocesar(client, 1, _CSV_BYTES)

    assert resp.status_code == 200
    assert "tok_200" not in servidor._sesion, "token de Ana debe eliminarse"
    assert "200"     not in servidor._sesion, "clave legajo de Ana debe eliminarse"
    assert "tok_100" in servidor._sesion,     "token de Juan debe permanecer"


def test_empleado_presente_permanece_en_sesion(monkeypatch, client):
    """
    Ambos empleados siguen en el nuevo CSV → ninguno se elimina de _sesion.
    """
    sesion = _sesion_dos_empleados()
    monkeypatch.setattr(servidor, "_sesion", sesion)
    monkeypatch.setattr(servidor, "_cargar_metadata", lambda: _meta())
    monkeypatch.setattr(
        servidor, "_procesar_empleados",
        lambda df, deptos: ([_emp_juan(), _emp_ana()], date(2025, 9, 1), date(2025, 9, 7)),
    )

    resp = _reprocesar(client, 1, _CSV_BYTES)

    assert resp.status_code == 200
    assert "tok_100" in servidor._sesion
    assert "tok_200" in servidor._sesion


def test_solo_legajos_no_elimina_ajenos(monkeypatch, client):
    """
    Con solo_legajos=100, el bloque de eliminación se saltea por completo.
    Ana (200) no debe eliminarse aunque no esté en el nuevo CSV.
    """
    sesion = _sesion_dos_empleados()
    monkeypatch.setattr(servidor, "_sesion", sesion)
    monkeypatch.setattr(servidor, "_cargar_metadata", lambda: _meta())
    monkeypatch.setattr(
        servidor, "_procesar_empleados",
        lambda df, deptos: ([_emp_juan()], date(2025, 9, 1), date(2025, 9, 7)),
    )

    resp = _reprocesar(client, 1, _CSV_BYTES, solo_legajos="100")

    assert resp.status_code == 200
    assert "tok_200" in servidor._sesion, "solo_legajos no debe eliminar otros empleados"
    assert "200"     in servidor._sesion


def test_sin_keyerror_con_legajo_inverso_ausente(monkeypatch, client):
    """
    tok_200 existe en la lista de la semana, pero '200' (clave inversa)
    NO está en _sesion.
    La guarda 'if leg_t in _sesion' debe evitar KeyError.
    Sin el hotfix, la línea 'del _sesion[leg_t] if ... else None' era SyntaxError.
    """
    sesion = {
        "tok_100": {
            "legajo": "100", "nombre": "Juan", "departamento": "REDES",
            "semana": 1, "semana_depto": 1,
            "confirmado": False, "confirmado_en": None,
            "dias": [], "totales": {}, "excluido_ot": False,
        },
        "100": {"legajo": "100"},
        "tok_200": {
            "legajo": "200", "nombre": "Ana", "departamento": "REDES",
            "semana": 1, "semana_depto": 1,
            "confirmado": False, "confirmado_en": None,
            "dias": [], "totales": {}, "excluido_ot": False,
        },
        # "200" intencionalmente ausente
    }
    monkeypatch.setattr(servidor, "_sesion", sesion)
    monkeypatch.setattr(servidor, "_cargar_metadata", lambda: _meta())
    monkeypatch.setattr(
        servidor, "_procesar_empleados",
        lambda df, deptos: ([_emp_juan()], date(2025, 9, 1), date(2025, 9, 7)),
    )

    resp = _reprocesar(client, 1, _CSV_BYTES)

    assert resp.status_code == 200, "no debe retornar 500 por KeyError"
    assert "tok_200" not in servidor._sesion
    assert "tok_100" in servidor._sesion


def test_token_fantasma_en_metadata_ignorado(monkeypatch, client):
    """
    tok_200 figura en la metadata de la semana pero ya no está en _sesion.
    El 'if t not in _sesion: continue' debe proteger la iteración.
    No debe lanzar excepción.
    """
    sesion = {
        "tok_100": {
            "legajo": "100", "nombre": "Juan", "departamento": "REDES",
            "semana": 1, "semana_depto": 1,
            "confirmado": False, "confirmado_en": None,
            "dias": [], "totales": {}, "excluido_ot": False,
        },
    }
    monkeypatch.setattr(servidor, "_sesion", sesion)
    # tok_200 en metadata pero no en _sesion
    monkeypatch.setattr(servidor, "_cargar_metadata",
                        lambda: _meta(tokens=["tok_100", "tok_200"]))
    monkeypatch.setattr(
        servidor, "_procesar_empleados",
        lambda df, deptos: ([_emp_juan()], date(2025, 9, 1), date(2025, 9, 7)),
    )

    resp = _reprocesar(client, 1, _CSV_BYTES)

    assert resp.status_code == 200
    assert "tok_100" in servidor._sesion
