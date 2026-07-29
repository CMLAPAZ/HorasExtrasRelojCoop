# -*- coding: utf-8 -*-
"""
test_puntualidad_db.py — Tests de la capa de persistencia de puntualidad.
Usa una base temporal; nunca toca puntualidad.db real.

Ejecutar:
    python -m pytest test_puntualidad_db.py -v
"""
import os
import shutil
import tempfile
from datetime import datetime

import pytest

from puntualidad_db import (
    obtener_ruta_db,
    inicializar_base_puntualidad,
    guardar_jornadas,
    guardar_resumenes_mensuales,
    consultar_jornadas_mes,
    consultar_resumen_mes,
    consultar_resumen_rango,
    consultar_acumulado_anual,
    consultar_tardanzas,
    mes_ya_procesado,
    eliminar_mes,
    registrar_importacion,
    justificar_jornada,
    desjustificar_jornada,
    reaplicar_justificaciones,
)

NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def tmp_base():
    d = tempfile.mkdtemp(prefix="punt_test_")
    inicializar_base_puntualidad(d)
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _jornada(legajo="10", fecha="2026-01-05", anio=2026, mes=1,
             tardanza=False, minutos=0, depto="redes"):
    return {
        "fecha": fecha, "anio": anio, "mes": mes, "departamento": depto,
        "legajo": legajo, "nombre": f"Empleado {legajo}",
        "hora_programada": "06:00",
        "hora_entrada": "06:08" if tardanza else "06:00",
        "minutos_tarde": minutos,
        "es_tarde": 1 if tardanza else 0,
        "estado_jornada": "TARDE" if tardanza else "PUNTUAL",
        "observacion": "",
        "origen": "TEST",
        "archivo_origen": "test.xlsx",
        "procesado_en": NOW,
    }


def _resumen(legajo="10", anio=2026, mes=1, tardanzas=0, minutos=0, depto="redes"):
    if tardanzas >= 5:
        estado = "NARANJA"
    elif tardanzas >= 3:
        estado = "AMARILLO"
    else:
        estado = "VERDE"
    return {
        "anio": anio, "mes": mes, "departamento": depto,
        "legajo": legajo, "nombre": f"Empleado {legajo}",
        "dias_evaluados": 20, "cantidad_tardanzas": tardanzas,
        "minutos_tarde": minutos, "estado_mensual": estado,
        "origen": "TEST", "archivo_origen": "test.xlsx", "procesado_en": NOW,
    }


# ── 1. Creación automática ────────────────────────────────────────────────────

def test_creacion_crea_carpeta_datos():
    d = tempfile.mkdtemp(prefix="punt_init_")
    try:
        assert not os.path.exists(os.path.join(d, "datos"))
        inicializar_base_puntualidad(d)
        assert os.path.exists(os.path.join(d, "datos"))
        assert os.path.exists(obtener_ruta_db(d))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_creacion_idempotente():
    d = tempfile.mkdtemp(prefix="punt_idem_")
    try:
        inicializar_base_puntualidad(d)
        inicializar_base_puntualidad(d)   # segunda llamada no debe fallar
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── 2. Inserción ──────────────────────────────────────────────────────────────

def test_insercion_jornada(tmp_base):
    guardar_jornadas(tmp_base, [_jornada()])
    rows = consultar_jornadas_mes(tmp_base, 2026, 1)
    assert len(rows) == 1
    assert rows[0]["legajo"] == "10"
    assert rows[0]["estado_jornada"] == "PUNTUAL"


def test_insercion_resumen(tmp_base):
    guardar_resumenes_mensuales(tmp_base, [_resumen(tardanzas=3)])
    rows = consultar_resumen_mes(tmp_base, 2026, 1)
    assert len(rows) == 1
    assert rows[0]["estado_mensual"] == "AMARILLO"
    assert rows[0]["cantidad_tardanzas"] == 3


# ── 3. Restricción de duplicados ──────────────────────────────────────────────

def test_duplicado_jornada_ignorado(tmp_base):
    j = _jornada()
    guardar_jornadas(tmp_base, [j])
    guardar_jornadas(tmp_base, [j])   # mismo (anio, mes, legajo, fecha)
    assert len(consultar_jornadas_mes(tmp_base, 2026, 1)) == 1


def test_duplicado_resumen_ignorado(tmp_base):
    r = _resumen()
    guardar_resumenes_mensuales(tmp_base, [r])
    guardar_resumenes_mensuales(tmp_base, [r])   # mismo (anio, mes, legajo)
    assert len(consultar_resumen_mes(tmp_base, 2026, 1)) == 1


# ── 4. Consulta mensual ───────────────────────────────────────────────────────

def test_consulta_mensual_sin_filtro(tmp_base):
    guardar_jornadas(tmp_base, [
        _jornada(legajo="10", fecha="2026-01-05", depto="redes"),
        _jornada(legajo="20", fecha="2026-01-06", depto="administracion"),
    ])
    rows = consultar_jornadas_mes(tmp_base, 2026, 1)
    assert len(rows) == 2


def test_consulta_mensual_filtra_departamento(tmp_base):
    guardar_jornadas(tmp_base, [
        _jornada(legajo="10", fecha="2026-01-05", depto="redes"),
        _jornada(legajo="20", fecha="2026-01-06", depto="administracion"),
    ])
    rows = consultar_jornadas_mes(tmp_base, 2026, 1, departamento="redes")
    assert len(rows) == 1
    assert rows[0]["legajo"] == "10"


def test_consulta_mensual_filtra_legajo(tmp_base):
    guardar_jornadas(tmp_base, [
        _jornada(legajo="10", fecha="2026-01-05"),
        _jornada(legajo="20", fecha="2026-01-06"),
    ])
    rows = consultar_jornadas_mes(tmp_base, 2026, 1, legajo="20")
    assert len(rows) == 1
    assert rows[0]["legajo"] == "20"


def test_consulta_no_mezcla_meses(tmp_base):
    guardar_jornadas(tmp_base, [
        _jornada(legajo="10", anio=2026, mes=1, fecha="2026-01-05"),
        _jornada(legajo="10", anio=2026, mes=2, fecha="2026-02-02"),
    ])
    assert len(consultar_jornadas_mes(tmp_base, 2026, 1)) == 1
    assert len(consultar_jornadas_mes(tmp_base, 2026, 2)) == 1


def test_consultar_tardanzas_mensual_y_anual(tmp_base):
    guardar_jornadas(tmp_base, [
        _jornada(legajo="10", fecha="2026-01-05", mes=1, tardanza=True, minutos=8),
        _jornada(legajo="10", fecha="2026-01-06", mes=1, tardanza=False),
        _jornada(legajo="10", fecha="2026-02-02", mes=2, tardanza=True, minutos=12),
    ])
    assert len(consultar_tardanzas(tmp_base, 2026, mes=1)) == 1
    assert len(consultar_tardanzas(tmp_base, 2026, legajo="10")) == 2


# ── 5. Acumulado anual ────────────────────────────────────────────────────────

def test_acumulado_suma_meses(tmp_base):
    guardar_resumenes_mensuales(tmp_base, [
        _resumen(legajo="10", mes=1, tardanzas=2, minutos=15),
        _resumen(legajo="10", mes=2, tardanzas=3, minutos=25),
        _resumen(legajo="10", mes=3, tardanzas=5, minutos=40),
    ])
    acum = consultar_acumulado_anual(tmp_base, 2026)
    assert len(acum) == 1
    assert acum[0]["cantidad_tardanzas"] == 10   # 2+3+5
    assert acum[0]["minutos_tarde"] == 80         # 15+25+40
    assert acum[0]["dias_evaluados"] == 60        # 20*3
    assert acum[0]["meses_incluidos"] == 3


def test_resumen_rango_suma_solo_meses_solicitados(tmp_base):
    guardar_resumenes_mensuales(tmp_base, [
        _resumen(legajo="10", mes=1, tardanzas=2, minutos=15),
        _resumen(legajo="10", mes=2, tardanzas=3, minutos=25),
        _resumen(legajo="10", mes=3, tardanzas=5, minutos=40),
    ])
    filas = consultar_resumen_rango(tmp_base, 2026, 2, 3)
    assert filas[0]["cantidad_tardanzas"] == 8
    assert filas[0]["minutos_tarde"] == 65
    assert filas[0]["meses_incluidos"] == 2


def test_acumulado_no_mezcla_años(tmp_base):
    guardar_resumenes_mensuales(tmp_base, [
        _resumen(legajo="10", anio=2026, mes=1, tardanzas=5),
        _resumen(legajo="10", anio=2027, mes=1, tardanzas=3),
    ])
    assert consultar_acumulado_anual(tmp_base, 2026)[0]["cantidad_tardanzas"] == 5
    assert consultar_acumulado_anual(tmp_base, 2027)[0]["cantidad_tardanzas"] == 3


def test_acumulado_filtra_departamento(tmp_base):
    guardar_resumenes_mensuales(tmp_base, [
        _resumen(legajo="10", mes=1, tardanzas=2, depto="redes"),
        _resumen(legajo="20", mes=1, tardanzas=4, depto="administracion"),
    ])
    rows = consultar_acumulado_anual(tmp_base, 2026, departamento="redes")
    assert len(rows) == 1
    assert rows[0]["legajo"] == "10"


def test_acumulado_no_mezcla_departamentos(tmp_base):
    guardar_resumenes_mensuales(tmp_base, [
        _resumen(legajo="10", mes=1, tardanzas=2, depto="redes"),
        _resumen(legajo="20", mes=1, tardanzas=4, depto="administracion"),
    ])
    rows = consultar_acumulado_anual(tmp_base, 2026)
    assert len(rows) == 2
    legajos = {r["legajo"] for r in rows}
    assert legajos == {"10", "20"}


# ── 6. Eliminación de un mes ──────────────────────────────────────────────────

def test_eliminar_mes_borra_jornadas_y_resumenes(tmp_base):
    guardar_jornadas(tmp_base, [
        _jornada(mes=1, fecha="2026-01-05"),
        _jornada(mes=2, anio=2026, fecha="2026-02-02"),
    ])
    guardar_resumenes_mensuales(tmp_base, [_resumen(mes=1), _resumen(mes=2)])

    resultado = eliminar_mes(tmp_base, 2026, 1)
    assert resultado["jornadas"] >= 1
    assert resultado["resumenes"] >= 1
    assert consultar_jornadas_mes(tmp_base, 2026, 1) == []
    assert consultar_resumen_mes(tmp_base, 2026, 1) == []


def test_eliminar_mes_no_toca_otros_meses(tmp_base):
    guardar_jornadas(tmp_base, [
        _jornada(mes=1, fecha="2026-01-05"),
        _jornada(mes=2, anio=2026, fecha="2026-02-02"),
    ])
    guardar_resumenes_mensuales(tmp_base, [_resumen(mes=1), _resumen(mes=2)])

    eliminar_mes(tmp_base, 2026, 1)
    assert len(consultar_jornadas_mes(tmp_base, 2026, 2)) == 1
    assert len(consultar_resumen_mes(tmp_base, 2026, 2)) == 1


# ── 7. Reemplazo de un mes ────────────────────────────────────────────────────

def test_reemplazo_jornada_actualiza_dato(tmp_base):
    guardar_jornadas(tmp_base, [_jornada(legajo="10", fecha="2026-01-05")])
    nuevo = _jornada(legajo="10", fecha="2026-01-05", tardanza=True, minutos=10)
    guardar_jornadas(tmp_base, [nuevo], reemplazar_mes=True)
    rows = consultar_jornadas_mes(tmp_base, 2026, 1)
    assert len(rows) == 1
    assert rows[0]["estado_jornada"] == "TARDE"
    assert rows[0]["minutos_tarde"] == 10


def test_reemplazo_resumen_actualiza_dato(tmp_base):
    guardar_resumenes_mensuales(tmp_base, [_resumen(tardanzas=1)])
    guardar_resumenes_mensuales(tmp_base, [_resumen(tardanzas=5)], reemplazar_mes=True)
    rows = consultar_resumen_mes(tmp_base, 2026, 1)
    assert len(rows) == 1
    assert rows[0]["cantidad_tardanzas"] == 5
    assert rows[0]["estado_mensual"] == "NARANJA"


def test_reemplazo_no_afecta_otros_meses(tmp_base):
    guardar_resumenes_mensuales(tmp_base, [
        _resumen(mes=1, tardanzas=1),
        _resumen(mes=2, tardanzas=2),
    ])
    guardar_resumenes_mensuales(tmp_base, [_resumen(mes=1, tardanzas=5)], reemplazar_mes=True)
    assert consultar_resumen_mes(tmp_base, 2026, 1)[0]["cantidad_tardanzas"] == 5
    assert consultar_resumen_mes(tmp_base, 2026, 2)[0]["cantidad_tardanzas"] == 2


# ── mes_ya_procesado ──────────────────────────────────────────────────────────

def test_mes_ya_procesado_false_al_inicio(tmp_base):
    assert not mes_ya_procesado(tmp_base, 2026, 1)


def test_mes_ya_procesado_true_despues_de_guardar(tmp_base):
    guardar_resumenes_mensuales(tmp_base, [_resumen(mes=1)])
    assert mes_ya_procesado(tmp_base, 2026, 1)
    assert not mes_ya_procesado(tmp_base, 2026, 2)


def test_mes_ya_procesado_false_despues_de_eliminar(tmp_base):
    guardar_resumenes_mensuales(tmp_base, [_resumen(mes=1)])
    eliminar_mes(tmp_base, 2026, 1)
    assert not mes_ya_procesado(tmp_base, 2026, 1)


# ── registrar_importacion ─────────────────────────────────────────────────────

def test_registrar_importacion_devuelve_id(tmp_base):
    nuevo_id = registrar_importacion(tmp_base, {
        "archivo_origen": "fichadas_enero.xlsx",
        "periodo_desde": "2026-01-01",
        "periodo_hasta": "2026-01-31",
        "registros_leidos": 500,
        "duplicados_omitidos": 3,
        "meses_procesados": "2026-01",
        "observacion": "Carga inicial",
        "procesado_en": NOW,
    })
    assert isinstance(nuevo_id, int) and nuevo_id > 0


def test_registrar_importacion_dos_registros(tmp_base):
    id1 = registrar_importacion(tmp_base, {"registros_leidos": 100, "procesado_en": NOW})
    id2 = registrar_importacion(tmp_base, {"registros_leidos": 200, "procesado_en": NOW})
    assert id2 > id1


# ── Justificación de tardanzas ────────────────────────────────────────────────

def _id_de(tmp_base, anio, mes, legajo, fecha):
    fila = next(
        j for j in consultar_jornadas_mes(tmp_base, anio, mes)
        if j["legajo"] == legajo and j["fecha"] == fecha
    )
    return fila["id"]


def test_justificar_jornada_marca_flag_y_motivo(tmp_base):
    guardar_jornadas(tmp_base, [_jornada(tardanza=True, minutos=8)])
    jid = _id_de(tmp_base, 2026, 1, "10", "2026-01-05")

    info = justificar_jornada(tmp_base, jid, "Turno médico")

    fila = consultar_jornadas_mes(tmp_base, 2026, 1)[0]
    assert fila["justificada"] == 1
    assert fila["motivo_justificacion"] == "Turno médico"
    assert info == {"anio": 2026, "mes": 1, "legajo": "10", "departamento": "redes"}


def test_justificar_jornada_id_inexistente_retorna_none(tmp_base):
    assert justificar_jornada(tmp_base, 999999, "motivo") is None


def test_justificar_jornada_no_tardanza_lanza_valueerror(tmp_base):
    guardar_jornadas(tmp_base, [_jornada(tardanza=False)])
    jid = _id_de(tmp_base, 2026, 1, "10", "2026-01-05")
    with pytest.raises(ValueError):
        justificar_jornada(tmp_base, jid, "motivo")


def test_desjustificar_jornada_revierte(tmp_base):
    guardar_jornadas(tmp_base, [_jornada(tardanza=True, minutos=8)])
    jid = _id_de(tmp_base, 2026, 1, "10", "2026-01-05")
    justificar_jornada(tmp_base, jid, "Turno médico")

    info = desjustificar_jornada(tmp_base, jid)

    fila = consultar_jornadas_mes(tmp_base, 2026, 1)[0]
    assert fila["justificada"] == 0
    assert fila["motivo_justificacion"] is None
    assert info["legajo"] == "10"


def test_desjustificar_jornada_id_inexistente_retorna_none(tmp_base):
    assert desjustificar_jornada(tmp_base, 999999) is None


def test_reaplicar_justificaciones_reaplica_por_clave_natural(tmp_base):
    guardar_jornadas(tmp_base, [_jornada(tardanza=True, minutos=8)])
    registros = [{
        "anio": 2026, "mes": 1, "legajo": "10", "fecha": "2026-01-05",
        "motivo_justificacion": "Turno médico",
    }]

    aplicadas = reaplicar_justificaciones(tmp_base, registros)

    assert aplicadas == 1
    fila = consultar_jornadas_mes(tmp_base, 2026, 1)[0]
    assert fila["justificada"] == 1
    assert fila["motivo_justificacion"] == "Turno médico"


def test_reaplicar_justificaciones_no_aplica_si_ya_no_es_tardanza(tmp_base):
    guardar_jornadas(tmp_base, [_jornada(tardanza=False)])
    registros = [{
        "anio": 2026, "mes": 1, "legajo": "10", "fecha": "2026-01-05",
        "motivo_justificacion": "Turno médico",
    }]

    aplicadas = reaplicar_justificaciones(tmp_base, registros)

    assert aplicadas == 0
    fila = consultar_jornadas_mes(tmp_base, 2026, 1)[0]
    assert fila["justificada"] == 0


def test_reaplicar_justificaciones_lista_vacia_no_falla(tmp_base):
    assert reaplicar_justificaciones(tmp_base, []) == 0


def test_guardar_resumenes_mensuales_persiste_cantidad_justificadas(tmp_base):
    resumen = _resumen(tardanzas=2)
    resumen["cantidad_justificadas"] = 3
    guardar_resumenes_mensuales(tmp_base, [resumen])

    fila = consultar_resumen_mes(tmp_base, 2026, 1)[0]
    assert fila["cantidad_justificadas"] == 3
