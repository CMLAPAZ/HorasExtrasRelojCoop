# -*- coding: utf-8 -*-
"""
Tests del importador historico de puntualidad.
Usan carpetas temporales y no tocan datos/puntualidad.db real.
"""
import os
import shutil
import tempfile

import pandas as pd
import pytest

from puntualidad_db import (
    consultar_jornadas_mes,
    consultar_resumen_mes,
    inicializar_base_puntualidad,
)
from puntualidad_importador import (
    detectar_periodo,
    importar_archivo_puntualidad,
    importar_carpeta_puntualidad,
    leer_archivo_fichadas,
)


@pytest.fixture
def tmp_base():
    d = tempfile.mkdtemp(prefix="punt_imp_base_")
    inicializar_base_puntualidad(d)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def tmp_archivos():
    d = tempfile.mkdtemp(prefix="punt_imp_arch_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def cfg_vacia(monkeypatch):
    monkeypatch.setattr("puntualidad_service.cargar_config", lambda: {})
    monkeypatch.setattr("puntualidad_service.cargar_feriados", lambda c: set())
    monkeypatch.setattr("puntualidad_service.cargar_dias_paro", lambda c: set())
    monkeypatch.setattr("puntualidad_service.cargar_asignaciones_especiales", lambda: [])


def _csv(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False, sep=";")
    return path


def _rows(legajo="10", fecha="2026-01-05", entrada="06:00", salida="13:00"):
    return [
        {
            "Nro. de usuario": legajo,
            "Fecha/Hora": f"{fecha} {entrada}",
            "Tipo de registro": "ENTRADA",
            "Departamento": "redes",
            "Nombre": f"Emp {legajo}",
        },
        {
            "Nro. de usuario": legajo,
            "Fecha/Hora": f"{fecha} {salida}",
            "Tipo de registro": "SALIDA",
            "Departamento": "redes",
            "Nombre": f"Emp {legajo}",
        },
    ]


def test_leer_archivo_csv_con_punto_y_coma(tmp_archivos):
    ruta = _csv(os.path.join(tmp_archivos, "enero.csv"), _rows())
    df = leer_archivo_fichadas(ruta)
    assert len(df) == 2
    assert "Fecha/Hora" in df.columns


def test_detectar_periodo(tmp_archivos):
    ruta = _csv(os.path.join(tmp_archivos, "enero.csv"), _rows(fecha="2026-01-05"))
    df = leer_archivo_fichadas(ruta)
    desde, hasta = detectar_periodo(df)
    assert desde.isoformat() == "2026-01-05"
    assert hasta.isoformat() == "2026-01-05"


def test_importar_archivo_crea_jornada_y_resumen(tmp_base, tmp_archivos, cfg_vacia):
    ruta = _csv(os.path.join(tmp_archivos, "enero.csv"), _rows())

    res = importar_archivo_puntualidad(tmp_base, ruta)

    assert res["jornadas_calculadas"] == 1
    assert res["jornadas_guardadas"] == 1
    jornadas = consultar_jornadas_mes(tmp_base, 2026, 1)
    resumen = consultar_resumen_mes(tmp_base, 2026, 1)
    assert len(jornadas) == 1
    assert len(resumen) == 1
    assert resumen[0]["estado_mensual"] == "VERDE"


def test_reimportar_sin_reemplazar_omite_duplicados(tmp_base, tmp_archivos, cfg_vacia):
    ruta = _csv(os.path.join(tmp_archivos, "enero.csv"), _rows())

    importar_archivo_puntualidad(tmp_base, ruta)
    res = importar_archivo_puntualidad(tmp_base, ruta)

    assert res["jornadas_guardadas"] == 0
    assert res["duplicados_omitidos"] == 1
    assert len(consultar_jornadas_mes(tmp_base, 2026, 1)) == 1
    assert len(consultar_resumen_mes(tmp_base, 2026, 1)) == 1


def test_reemplazar_mes_actualiza_datos(tmp_base, tmp_archivos, cfg_vacia):
    ruta_ok = _csv(os.path.join(tmp_archivos, "enero_ok.csv"), _rows(entrada="06:00"))
    ruta_tarde = _csv(os.path.join(tmp_archivos, "enero_tarde.csv"), _rows(entrada="06:10"))

    importar_archivo_puntualidad(tmp_base, ruta_ok)
    importar_archivo_puntualidad(tmp_base, ruta_tarde, reemplazar_mes=True)

    jornadas = consultar_jornadas_mes(tmp_base, 2026, 1)
    resumen = consultar_resumen_mes(tmp_base, 2026, 1)
    assert len(jornadas) == 1
    assert jornadas[0]["estado_jornada"] == "TARDE"
    assert resumen[0]["cantidad_tardanzas"] == 1


def test_importar_carpeta_procesa_archivos_ordenados(tmp_base, tmp_archivos, cfg_vacia):
    _csv(os.path.join(tmp_archivos, "2026-01.csv"), _rows(legajo="10", fecha="2026-01-05"))
    _csv(os.path.join(tmp_archivos, "2026-02.csv"), _rows(legajo="20", fecha="2026-02-02"))

    res = importar_carpeta_puntualidad(tmp_base, tmp_archivos)

    assert len(res["importados"]) == 2
    assert res["errores"] == []
    assert len(consultar_resumen_mes(tmp_base, 2026, 1)) == 1
    assert len(consultar_resumen_mes(tmp_base, 2026, 2)) == 1


def test_importar_carpeta_continua_con_errores(tmp_base, tmp_archivos, cfg_vacia):
    _csv(os.path.join(tmp_archivos, "2026-01.csv"), _rows())
    _csv(os.path.join(tmp_archivos, "mal.csv"), [{"otra": "columna"}])

    res = importar_carpeta_puntualidad(
        tmp_base,
        tmp_archivos,
        continuar_con_errores=True,
    )

    assert len(res["importados"]) == 1
    assert len(res["errores"]) == 1
