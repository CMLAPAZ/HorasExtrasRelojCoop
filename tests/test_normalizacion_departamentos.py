# -*- coding: utf-8 -*-
"""
Normalización centralizada de departamentos (Problema 1: "dos grupos REDES").

_normalizar_departamento_web / _nombre_departamento_visible reconocen los 5
departamentos canónicos (Redes, Administración, Guardias, Internet,
Telefonía) y devuelven siempre el nombre visible oficial (con tildes y
capitalización), sin importar mayúsculas/minúsculas, espacios o acentos de
entrada.

_empleados_conocidos() aplica esa normalización a sus 3 fuentes
(empleados_extra, periodo_empleados, _sesion) para que un mismo
departamento no quede dividido en dos grupos en /francos y /francos/saldos
cuando las fuentes usan capitalización distinta (ej. "redes" en sesión vs.
"Redes" en periodo_empleados — caso Zabala).
"""
import pytest
import servidor


# ──────────────────────────────────────────────────────────────
# 1-5. Variantes de cada departamento -> nombre canónico visible
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("variante", [
    "redes", "REDES", "Redes", " redes ", "rede", "RED", "Red",
])
def test_variantes_redes(variante):
    assert servidor._nombre_departamento_visible(variante) == "Redes"


@pytest.mark.parametrize("variante", [
    "administracion", "ADMINISTRACION", "Administración", "ADMINISTRACIÓN",
    " administracion", "admin", "administrativo", "Administraciom",
])
def test_variantes_administracion(variante):
    assert servidor._nombre_departamento_visible(variante) == "Administración"


@pytest.mark.parametrize("variante", [
    "guardias", "GUARDIAS", "Guardias", "guardia", "Guardia ", " GUARDIA",
])
def test_variantes_guardias(variante):
    assert servidor._nombre_departamento_visible(variante) == "Guardias"


@pytest.mark.parametrize("variante", [
    "internet", "INTERNET", "Internet", " internet ", "INTERNET ",
])
def test_variantes_internet(variante):
    assert servidor._nombre_departamento_visible(variante) == "Internet"


@pytest.mark.parametrize("variante", [
    "telefonia", "TELEFONIA", "Telefonía", "TELEFONÍA", "telefono",
    "Telefono", "telefonos", "TELÉFONOS", " telefonia ",
])
def test_variantes_telefonia(variante):
    assert servidor._nombre_departamento_visible(variante) == "Telefonía"


# ──────────────────────────────────────────────────────────────
# Fixtures: DB temporal con esquema completo (vía _init_db) + cliente Flask
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def db_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(servidor, "DATOS_DIR", tmp_path)
    monkeypatch.setattr(servidor, "DB_FILE", tmp_path / "cierres_test.db")
    servidor._init_db()


@pytest.fixture(autouse=True)
def _patch_io(monkeypatch):
    monkeypatch.setattr(servidor, "_autenticado", lambda: True)


@pytest.fixture
def client():
    servidor.app.config["TESTING"] = True
    with servidor.app.test_client() as c:
        yield c


# ──────────────────────────────────────────────────────────────
# 6. Fuentes mixtas redes/Redes -> un único grupo (caso Zabala)
# ──────────────────────────────────────────────────────────────

def test_empleados_conocidos_unifica_redes_minuscula_y_mayuscula(db_temporal, monkeypatch):
    # Zabala (133): solo en periodo_empleados, con "Redes" (capitalizado,
    # vía _calcular_periodo -> _nombre_departamento_visible al cerrar).
    with servidor._get_db() as conn:
        conn.execute(
            "INSERT INTO periodo_empleados (periodo_id, legajo, nombre, departamento) VALUES (1,?,?,?)",
            ("133", "ZABALA ANTONIO", "Redes"),
        )
        conn.commit()

    # Resto del depto: token activo en sesión con "redes" (minúscula, vía
    # _normalizar_departamento_web en /procesar).
    monkeypatch.setattr(servidor, "_sesion", {
        "tok_1": {"legajo": "1", "nombre": "OTRO EMPLEADO", "departamento": "redes"},
    })

    empleados = servidor._empleados_conocidos()
    deptos = {e["legajo"]: e["departamento"] for e in empleados}

    assert deptos["133"] == "Redes"
    assert deptos["1"] == "Redes"

    grupos = {e["departamento"] for e in empleados}
    assert grupos == {"Redes"}, f"Debe quedar un único grupo 'Redes', no {grupos}"


# ──────────────────────────────────────────────────────────────
# 7. Sin regresión para Guardias / Internet / Telefonía
# ──────────────────────────────────────────────────────────────

def test_empleados_conocidos_sin_regresion_otros_deptos(db_temporal, monkeypatch):
    with servidor._get_db() as conn:
        conn.execute(
            "INSERT INTO empleados_extra (legajo, nombre, departamento, activo) VALUES (?,?,?,1)",
            ("113", "MAYDANA", "GUARDIAS"),
        )
        conn.execute(
            "INSERT INTO empleados_extra (legajo, nombre, departamento, activo) VALUES (?,?,?,1)",
            ("50", "GOMEZ NESTOR", "internet"),
        )
        conn.execute(
            "INSERT INTO empleados_extra (legajo, nombre, departamento, activo) VALUES (?,?,?,1)",
            ("16", "BAROLIN FRANCA", "Telefonia"),  # cargado sin tilde
        )
        conn.commit()

    monkeypatch.setattr(servidor, "_sesion", {})

    empleados = servidor._empleados_conocidos()
    deptos = {e["legajo"]: e["departamento"] for e in empleados}

    assert deptos["113"] == "Guardias"
    assert deptos["50"] == "Internet"
    assert deptos["16"] == "Telefonía"


def test_francos_prioriza_ingenieros_sobre_sesion_vieja(db_temporal, monkeypatch):
    monkeypatch.setattr(servidor, "_sesion", {
        "tok_100": {"legajo": "100", "nombre": "MANCIONI MARTIN", "departamento": "redes"},
        "tok_101": {"legajo": "101", "nombre": "GATTI MARCELO", "departamento": "Redes"},
    })

    empleados = {e["legajo"]: e for e in servidor._empleados_conocidos()}

    assert empleados["100"] == {
        "legajo": "100", "nombre": "MANCIONI, Martin", "departamento": "Ingenieros",
    }
    assert empleados["101"] == {
        "legajo": "101", "nombre": "GATTI, Marcelo", "departamento": "Ingenieros",
    }


# ──────────────────────────────────────────────────────────────
# 8. /francos y /francos/saldos: un único grupo por depto canónico
# ──────────────────────────────────────────────────────────────

def _preparar_redes_mixto(monkeypatch):
    with servidor._get_db() as conn:
        conn.execute(
            "INSERT INTO periodo_empleados (periodo_id, legajo, nombre, departamento) VALUES (1,?,?,?)",
            ("133", "ZABALA ANTONIO", "Redes"),
        )
        conn.commit()
    monkeypatch.setattr(servidor, "_sesion", {
        "tok_1": {"legajo": "1", "nombre": "OTRO EMPLEADO", "departamento": "redes"},
    })


def test_francos_saldos_un_unico_grupo_redes(db_temporal, monkeypatch, client):
    _preparar_redes_mixto(monkeypatch)

    resp = client.get("/francos/saldos")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert body.count('class="fila-depto" data-depto="Redes"') == 1
    assert 'data-depto="redes"' not in body


def test_francos_un_unico_grupo_redes(db_temporal, monkeypatch, client):
    _preparar_redes_mixto(monkeypatch)

    resp = client.get("/francos")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert body.count('class="fila-depto-f" data-depto="Redes"') == 1
    assert 'data-depto="redes"' not in body
