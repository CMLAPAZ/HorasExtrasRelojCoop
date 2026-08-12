# -*- coding: utf-8 -*-
"""
reprocesar_semana() con solo_legajos (corrección de uno o pocos empleados)
actualizaba _sesion/confirmaciones correctamente, pero se SALTEABA por
completo la actualización de semana_N.csv ("parcial no reemplaza el
archivo") para no perder a los demás empleados con un archivo que solo
trae a algunos. Eso dejaba el CSV desactualizado PARA SIEMPRE para el
legajo corregido: cualquier informe que releyera el CSV desde cero ("Ver
acumulado", "Informe de fichadas") seguía mostrando el valor viejo, sin
ningún aviso, aunque periodo_empleados/confirmaciones ya tuvieran el dato
correcto.

Caso real (12/08/2026): legajo 150 (MELGAREJO MANUEL, Redes) fue
corregido individualmente el 02/08 después de cargar la semana 5 de
julio -- el cierre #7 mostraba su OT100 correcto (38h) en todos lados
salvo en "Ver acumulado", que seguía mostrando el valor viejo (36h)
porque leía semana_5.csv directamente y ese archivo nunca se actualizó.

Fix: en el caso solo_legajos, se sacan del CSV existente las filas de
los legajos corregidos y se agregan las filas nuevas de esos mismos
legajos desde el archivo subido -- el resto de los empleados del CSV
queda intacto.
"""
import io
from datetime import date

import pandas as pd
import pytest

import servidor


@pytest.fixture
def semanas_dir(tmp_path, monkeypatch):
    d = tmp_path / "semanas"
    d.mkdir()
    monkeypatch.setattr(servidor, "SEMANAS_DIR", d)
    return d


@pytest.fixture(autouse=True)
def _patch_io(monkeypatch):
    monkeypatch.setattr(servidor, "_autenticado", lambda: True)
    monkeypatch.setattr(servidor, "_guardar_sesion", lambda s: None)
    monkeypatch.setattr(servidor, "_guardar_metadata", lambda m: None)
    monkeypatch.setattr(servidor, "_wa_url", lambda *a, **kw: "")


@pytest.fixture
def client():
    servidor.app.config["TESTING"] = True
    with servidor.app.test_client() as c:
        yield c


def _sesion_dos_empleados():
    return {
        "tok_150": {
            "legajo": "150", "nombre": "MELGAREJO MANUEL", "departamento": "REDES",
            "semana": 1, "semana_depto": 1,
            "confirmado": False, "confirmado_en": None,
            "dias": [], "totales": {}, "excluido_ot": False,
        },
        "150": {"legajo": "150"},
        "tok_200": {
            "legajo": "200", "nombre": "OTRO EMPLEADO", "departamento": "REDES",
            "semana": 1, "semana_depto": 1,
            "confirmado": False, "confirmado_en": None,
            "dias": [], "totales": {}, "excluido_ot": False,
        },
        "200": {"legajo": "200"},
    }


def _meta():
    return {
        "semanas": [{
            "numero": 1, "num_depto": 1, "departamento": "REDES",
            "tokens": ["tok_150", "tok_200"],
        }],
    }


def _emp_150():
    return {"legajo": "150", "nombre": "MELGAREJO MANUEL", "registros": [], "excluido_ot": False}


def test_reprocesar_parcial_actualiza_solo_las_filas_del_legajo_corregido(
    semanas_dir, monkeypatch, client
):
    # CSV original en disco: legajo 150 (dato viejo) + legajo 200 (sin tocar).
    original = pd.DataFrame([
        {"Legajo": "150", "Nombre": "MELGAREJO MANUEL", "Departamento": "REDES",
         "FechaHora": "2026-07-27 06:00:00", "Tipo": "ENTRADA"},
        {"Legajo": "150", "Nombre": "MELGAREJO MANUEL", "Departamento": "REDES",
         "FechaHora": "2026-07-27 14:00:00", "Tipo": "SALIDA"},
        {"Legajo": "200", "Nombre": "OTRO EMPLEADO", "Departamento": "REDES",
         "FechaHora": "2026-07-27 06:00:00", "Tipo": "ENTRADA"},
        {"Legajo": "200", "Nombre": "OTRO EMPLEADO", "Departamento": "REDES",
         "FechaHora": "2026-07-27 14:00:00", "Tipo": "SALIDA"},
    ])
    servidor._guardar_semana_csv(1, original)

    sesion = _sesion_dos_empleados()
    monkeypatch.setattr(servidor, "_sesion", sesion)
    monkeypatch.setattr(servidor, "_cargar_metadata", lambda: _meta())
    monkeypatch.setattr(
        servidor, "_procesar_empleados",
        lambda df, deptos: ([_emp_150()], date(2026, 7, 27), date(2026, 8, 2)),
    )

    # Archivo corregido: SOLO trae al legajo 150, con una fichada nueva.
    # _leer_archivo prueba separador ";" antes que "," -- usarlo acá para
    # que se parsee en columnas reales, igual que un archivo real.
    csv_corregido = (
        "Nro. de usuario;Nombre;Departamento;Fecha/Hora;Tipo de registro\n"
        "150;MELGAREJO MANUEL;REDES;2026-07-27 05:30:00;ENTRADA\n"
        "150;MELGAREJO MANUEL;REDES;2026-07-27 14:00:00;SALIDA\n"
    ).encode("utf-8")

    resp = client.post(
        "/semanas/1/reprocesar",
        data={"csv": (io.BytesIO(csv_corregido), "fix_150.csv"), "solo_legajos": "150"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    resultado = servidor._cargar_semana_csv(1)
    resultado = servidor._normalizar_columnas(resultado)

    # Legajo 200 sigue intacto (2 filas, sin tocar).
    filas_200 = resultado[resultado["Legajo"].astype(str) == "200"]
    assert len(filas_200) == 2

    # Legajo 150 ahora tiene las filas NUEVAS (entrada 05:30, no 06:00).
    filas_150 = resultado[resultado["Legajo"].astype(str) == "150"]
    assert len(filas_150) == 2
    horas_entrada = set(filas_150["FechaHora"].astype(str))
    assert any("05:30:00" in h for h in horas_entrada), (
        "el CSV en disco debe reflejar la fichada corregida, no la vieja "
        "(06:00:00) -- si sigue con la vieja, el fix de merge no se aplicó"
    )
    assert not any("06:00:00" in h for h in horas_entrada)
