# -*- coding: utf-8 -*-
"""
/admin/corregir-punch/<n>: corrige un punch puntual (fila) en un
semana_N.csv ya en disco, identificado por legajo+fecha+tipo+hora vieja
exacta. Dry-run por default, ?confirmar=si aplica.

Caso real (13/08/2026): legajo 150 (MELGAREJO MANUEL) tenía una SALIDA
mal cargada el 2026-08-02 (13:00:00 en vez de 15:00:00) que había sido
corregida en la confirmación/periodo_empleados pero nunca en el
semana_18.csv (bug de reprocesar_semana con solo_legajos, ya arreglado
por separado) -- esta ruta permite corregir el CSV histórico sin tener
que resubir el archivo entero.
"""
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


@pytest.fixture
def client():
    servidor.app.config["TESTING"] = True
    with servidor.app.test_client() as c:
        yield c


def _csv_con_punch_viejo(semanas_dir):
    df = pd.DataFrame([
        {"Legajo": "150", "Nombre": "MELGAREJO MANUEL", "Departamento": "REDES",
         "FechaHora": "2026-08-02 07:02:58", "Tipo": "ENTRADA"},
        {"Legajo": "150", "Nombre": "MELGAREJO MANUEL", "Departamento": "REDES",
         "FechaHora": "2026-08-02 13:00:00", "Tipo": "SALIDA"},
        {"Legajo": "200", "Nombre": "OTRO", "Departamento": "REDES",
         "FechaHora": "2026-08-02 06:00:00", "Tipo": "ENTRADA"},
    ])
    servidor._guardar_semana_csv(18, df)


def test_dry_run_no_aplica_nada(semanas_dir, client):
    _csv_con_punch_viejo(semanas_dir)
    resp = client.get(
        "/admin/corregir-punch/18",
        query_string={"legajo": "150", "fecha": "2026-08-02", "tipo": "SALIDA",
                       "hora_vieja": "13:00:00", "hora_nueva": "15:00:00"},
    )
    data = resp.get_json()
    assert data["coincidencias"] == 1
    assert data["aplicado"] is False

    df = servidor._normalizar_columnas(servidor._cargar_semana_csv(18))
    assert "2026-08-02 13:00:00" in df["FechaHora"].astype(str).values, "sin confirmar=si no debe tocar el CSV"


def test_confirmar_si_corrige_solo_la_fila_indicada(semanas_dir, client):
    _csv_con_punch_viejo(semanas_dir)
    resp = client.get(
        "/admin/corregir-punch/18",
        query_string={"legajo": "150", "fecha": "2026-08-02", "tipo": "SALIDA",
                       "hora_vieja": "13:00:00", "hora_nueva": "15:00:00", "confirmar": "si"},
    )
    data = resp.get_json()
    assert data["aplicado"] is True

    df = servidor._normalizar_columnas(servidor._cargar_semana_csv(18))
    fechas = set(df["FechaHora"].astype(str))
    assert "2026-08-02 15:00:00" in fechas
    assert "2026-08-02 13:00:00" not in fechas
    # Las demás filas (entrada de 150, y todo lo de legajo 200) intactas.
    assert "2026-08-02 07:02:58" in fechas
    assert "2026-08-02 06:00:00" in fechas
    assert len(df) == 3


def test_sin_coincidencia_exacta_no_aplica(semanas_dir, client):
    _csv_con_punch_viejo(semanas_dir)
    resp = client.get(
        "/admin/corregir-punch/18",
        query_string={"legajo": "150", "fecha": "2026-08-02", "tipo": "SALIDA",
                       "hora_vieja": "99:00:00", "hora_nueva": "15:00:00", "confirmar": "si"},
    )
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["coincidencias"] == 0
    assert data["aplicado"] is False
