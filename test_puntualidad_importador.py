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
    convertir_sin_entrada_a_tardanza_manual,
    inicializar_base_puntualidad,
    justificar_jornada,
)
from puntualidad_importador import (
    detectar_periodo,
    importar_archivo_puntualidad,
    importar_carpeta_puntualidad,
    leer_archivo_fichadas,
    recalcular_resumen_mes,
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


def test_importar_dos_semanas_mismo_mes_acumula_resumen(tmp_base, tmp_archivos, cfg_vacia):
    """El resumen mensual debe reflejar TODAS las jornadas del mes ya guardadas,
    no solo las del archivo importado en último lugar -- un mes suele cargarse
    en varios archivos semanales (una por semana de fichadas)."""
    semana1 = _csv(os.path.join(tmp_archivos, "semana1.csv"),
                    _rows(legajo="10", fecha="2026-01-05", entrada="06:00"))
    semana2 = _csv(os.path.join(tmp_archivos, "semana2.csv"),
                    _rows(legajo="10", fecha="2026-01-12", entrada="06:10"))

    importar_archivo_puntualidad(tmp_base, semana1)
    importar_archivo_puntualidad(tmp_base, semana2)

    jornadas = consultar_jornadas_mes(tmp_base, 2026, 1)
    resumen = consultar_resumen_mes(tmp_base, 2026, 1)
    assert len(jornadas) == 2
    assert len(resumen) == 1
    assert resumen[0]["dias_evaluados"] == 2
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


def test_recalcular_resumen_mes_no_afecta_otro_legajo(tmp_base, tmp_archivos, cfg_vacia):
    filas = _rows(legajo="10", fecha="2026-01-05", entrada="06:10") + \
        _rows(legajo="20", fecha="2026-01-05", entrada="06:10")
    ruta = _csv(os.path.join(tmp_archivos, "enero.csv"), filas)
    importar_archivo_puntualidad(tmp_base, ruta)

    jid_10 = next(
        j["id"] for j in consultar_jornadas_mes(tmp_base, 2026, 1) if j["legajo"] == "10"
    )
    justificar_jornada(tmp_base, jid_10, "Turno médico")
    recalcular_resumen_mes(tmp_base, 2026, 1)

    resumen = {r["legajo"]: r for r in consultar_resumen_mes(tmp_base, 2026, 1)}
    assert resumen["10"]["cantidad_tardanzas"] == 0
    assert resumen["10"]["cantidad_justificadas"] == 1
    assert resumen["20"]["cantidad_tardanzas"] == 1
    assert resumen["20"]["cantidad_justificadas"] == 0


def test_reemplazar_mes_preserva_justificaciones(tmp_base, tmp_archivos, cfg_vacia):
    ruta_tarde = _csv(os.path.join(tmp_archivos, "enero_tarde.csv"), _rows(entrada="06:10"))
    importar_archivo_puntualidad(tmp_base, ruta_tarde)

    jid = consultar_jornadas_mes(tmp_base, 2026, 1)[0]["id"]
    justificar_jornada(tmp_base, jid, "Turno médico")

    ruta_tarde2 = _csv(os.path.join(tmp_archivos, "enero_tarde2.csv"), _rows(entrada="06:12"))
    importar_archivo_puntualidad(tmp_base, ruta_tarde2, reemplazar_mes=True)

    jornadas = consultar_jornadas_mes(tmp_base, 2026, 1)
    assert len(jornadas) == 1
    assert jornadas[0]["justificada"] == 1
    assert jornadas[0]["motivo_justificacion"] == "Turno médico"

    resumen = consultar_resumen_mes(tmp_base, 2026, 1)
    assert resumen[0]["cantidad_tardanzas"] == 0
    assert resumen[0]["cantidad_justificadas"] == 1


def _rows_solo_salida(legajo="10", fecha="2026-01-05", salida="13:00"):
    """Una fichada con SALIDA pero sin ENTRADA -> genera estado SIN_ENTRADA."""
    return [{
        "Nro. de usuario": legajo,
        "Fecha/Hora": f"{fecha} {salida}",
        "Tipo de registro": "SALIDA",
        "Departamento": "redes",
        "Nombre": f"Emp {legajo}",
    }]


def test_reemplazar_mes_preserva_tardanza_manual(tmp_base, tmp_archivos, cfg_vacia):
    ruta = _csv(os.path.join(tmp_archivos, "enero.csv"), _rows_solo_salida())
    importar_archivo_puntualidad(tmp_base, ruta)

    jornadas = consultar_jornadas_mes(tmp_base, 2026, 1)
    assert len(jornadas) == 1
    assert jornadas[0]["estado_jornada"] == "SIN_ENTRADA"
    convertir_sin_entrada_a_tardanza_manual(tmp_base, jornadas[0]["id"], "Ausencia avisada")

    ruta2 = _csv(os.path.join(tmp_archivos, "enero2.csv"), _rows_solo_salida(salida="13:05"))
    importar_archivo_puntualidad(tmp_base, ruta2, reemplazar_mes=True)

    jornadas = consultar_jornadas_mes(tmp_base, 2026, 1)
    assert len(jornadas) == 1
    assert jornadas[0]["es_tarde"] == 1
    assert jornadas[0]["origen"] == "MANUAL"
    assert jornadas[0]["justificada"] == 1
    assert jornadas[0]["motivo_justificacion"] == "Ausencia avisada"

    resumen = consultar_resumen_mes(tmp_base, 2026, 1)
    assert resumen[0]["cantidad_tardanzas"] == 0
    assert resumen[0]["cantidad_justificadas"] == 1
