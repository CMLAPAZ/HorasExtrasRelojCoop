# -*- coding: utf-8 -*-
"""
test_puntualidad_service.py — Tests del motor de Control de Puntualidad.

Usa DataFrames construidos en memoria. No usa archivos reales.
No modifica config.json. Usa monkeypatch para aislar de cargar_config() y friends.

Ejecutar:
    python -m pytest test_puntualidad_service.py -v
"""
import pytest
import pandas as pd

from puntualidad_service import (
    normalizar_archivo_fichadas,
    filtrar_periodo,
    calcular_jornadas_puntualidad,
    resumir_por_mes,
    obtener_estado_mensual,
    obtener_estado_anual,
    obtener_estado_visual,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _df(*rows, depto="redes"):
    """
    Crea un DataFrame mínimo de fichadas.
    Cada row: (legajo, fecha 'YYYY-MM-DD', hora 'HH:MM', tipo[, depto[, nombre]])
    """
    records = []
    for row in rows:
        leg, fecha, hora, tipo = row[0], row[1], row[2], row[3]
        dep = row[4] if len(row) > 4 else depto
        nom = row[5] if len(row) > 5 else f"Emp {leg}"
        records.append({
            "Legajo":       str(leg),
            "FechaHora":    pd.Timestamp(f"{fecha} {hora}"),
            "Tipo":         tipo,
            "Departamento": dep,
            "Nombre":       nom,
        })
    return pd.DataFrame(records)


def _jornada_manual(**kwargs):
    """Dict de jornada con valores por defecto para tests de resumir_por_mes."""
    base = {
        "fecha": "2026-01-05", "anio": 2026, "mes": 1,
        "departamento": "redes", "legajo": "10", "nombre": "Emp 10",
        "hora_programada": "06:00", "hora_entrada": "06:00",
        "minutos_tarde": 0, "es_tarde": 0, "estado_jornada": "PUNTUAL",
        "observacion": "", "origen": "CALCULO_AUTOMATICO",
        "archivo_origen": "", "procesado_en": "2026-07-15 10:00:00",
    }
    base.update(kwargs)
    return base


@pytest.fixture
def cfg_vacia(monkeypatch):
    """Aisla de config.json real: sin feriados, sin paro, sin asignaciones."""
    monkeypatch.setattr("puntualidad_service.cargar_config", lambda: {})
    monkeypatch.setattr("puntualidad_service.cargar_feriados", lambda c: set())
    monkeypatch.setattr("puntualidad_service.cargar_dias_paro", lambda c: set())
    monkeypatch.setattr("puntualidad_service.cargar_asignaciones_especiales", lambda: [])


# ─── 1. Empleado puntual a las 06:00 ─────────────────────────────────────────

def test_puntual_exacto(cfg_vacia):
    df = _df(("10", "2026-01-05", "06:00", "ENTRADA"),
             ("10", "2026-01-05", "13:00", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next(x for x in js if x["fecha"] == "2026-01-05")
    assert j["estado_jornada"] == "PUNTUAL"
    assert j["es_tarde"] == 0
    assert j["minutos_tarde"] == 0


# ─── 2. Entrada a 06:05: dentro de tolerancia (< 6 min) ─────────────────────

def test_tolerancia_cinco_minutos(cfg_vacia):
    df = _df(("10", "2026-01-05", "06:05", "ENTRADA"),
             ("10", "2026-01-05", "13:00", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next(x for x in js if x["fecha"] == "2026-01-05")
    assert j["estado_jornada"] == "PUNTUAL"
    assert j["es_tarde"] == 0


# ─── 3. Entrada a 06:06: tardanza (>= 6 min) ─────────────────────────────────

def test_tardanza_seis_minutos(cfg_vacia):
    df = _df(("10", "2026-01-05", "06:06", "ENTRADA"),
             ("10", "2026-01-05", "13:00", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next(x for x in js if x["fecha"] == "2026-01-05")
    assert j["estado_jornada"] == "TARDE"
    assert j["es_tarde"] == 1
    assert j["minutos_tarde"] == 6


# ─── 4. Entrada antes del horario: minutos_tarde = 0 (no negativos) ──────────

def test_entrada_anticipada_minutos_cero(cfg_vacia):
    df = _df(("10", "2026-01-05", "05:30", "ENTRADA"),
             ("10", "2026-01-05", "12:30", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next(x for x in js if x["fecha"] == "2026-01-05")
    assert j["minutos_tarde"] == 0
    assert j["es_tarde"] == 0


# ─── 5. Primera entrada entre varias entradas del día ─────────────────────────

def test_primera_entrada_entre_varias(cfg_vacia):
    # Dos ENTRADA seguidas (sin SALIDA intermedia):
    # _limpiar_y_emparejar produce (06:00,06:00) incompleto + usa 07:00 como nueva entrada
    # La primera ENTRADA real es 06:00 → puntual
    df = _df(("10", "2026-01-05", "06:00", "ENTRADA"),
             ("10", "2026-01-05", "07:00", "ENTRADA"),
             ("10", "2026-01-05", "13:00", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next(x for x in js if x["fecha"] == "2026-01-05")
    assert j["hora_entrada"] == "06:00"


# ─── 6. Duplicado exacto de fichada ──────────────────────────────────────────

def test_duplicado_exacto_ignorado(cfg_vacia):
    df = _df(("10", "2026-01-05", "06:00", "ENTRADA"),
             ("10", "2026-01-05", "06:00", "ENTRADA"),   # duplicado
             ("10", "2026-01-05", "13:00", "SALIDA"))
    df_orig_len = len(df)
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next(x for x in js if x["fecha"] == "2026-01-05")
    assert j["hora_entrada"] == "06:00"
    assert j["estado_jornada"] == "PUNTUAL"
    assert len(df) == df_orig_len   # original sin cambiar


# ─── 7. Sin ENTRADA (solo SALIDA): SIN_ENTRADA ────────────────────────────────

def test_sin_entrada(cfg_vacia):
    df = _df(("10", "2026-01-05", "13:00", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next((x for x in js if x["fecha"] == "2026-01-05"), None)
    if j is not None:
        assert j["estado_jornada"] == "SIN_ENTRADA"
        assert j["es_tarde"] == 0


# ─── 8. Jornada incompleta (ENTRADA sin SALIDA) ───────────────────────────────

def test_jornada_incompleta(cfg_vacia):
    df = _df(("10", "2026-01-05", "06:00", "ENTRADA"))   # sin SALIDA
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next(x for x in js if x["fecha"] == "2026-01-05")
    assert j["estado_jornada"] == "INCOMPLETA"


# ─── 9. Sábado: FIN_DE_SEMANA ────────────────────────────────────────────────

def test_sabado_fin_de_semana(cfg_vacia):
    # 2026-01-03 es sábado
    df = _df(("10", "2026-01-03", "06:00", "ENTRADA"),
             ("10", "2026-01-03", "10:00", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next(x for x in js if x["fecha"] == "2026-01-03")
    assert j["estado_jornada"] == "FIN_DE_SEMANA"
    assert j["es_tarde"] == 0


# ─── 10. Domingo: FIN_DE_SEMANA ───────────────────────────────────────────────

def test_domingo_fin_de_semana(cfg_vacia):
    # 2026-01-04 es domingo
    df = _df(("10", "2026-01-04", "06:00", "ENTRADA"),
             ("10", "2026-01-04", "10:00", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next(x for x in js if x["fecha"] == "2026-01-04")
    assert j["estado_jornada"] == "FIN_DE_SEMANA"


# ─── 11. Feriado ─────────────────────────────────────────────────────────────

def test_feriado(cfg_vacia):
    from datetime import date as d_
    feriado = {d_(2026, 1, 5)}
    df = _df(("10", "2026-01-05", "06:00", "ENTRADA"),
             ("10", "2026-01-05", "13:00", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=feriado)
    j = next(x for x in js if x["fecha"] == "2026-01-05")
    assert j["estado_jornada"] == "FERIADO"
    assert j["es_tarde"] == 0


# ─── 12. Día de paro ──────────────────────────────────────────────────────────

def test_dia_de_paro(monkeypatch):
    monkeypatch.setattr("puntualidad_service.cargar_config", lambda: {})
    monkeypatch.setattr("puntualidad_service.cargar_feriados", lambda c: set())
    monkeypatch.setattr("puntualidad_service.cargar_dias_paro", lambda c: {"2026-01-05"})
    monkeypatch.setattr("puntualidad_service.cargar_asignaciones_especiales", lambda: [])

    df = _df(("10", "2026-01-05", "06:00", "ENTRADA"),
             ("10", "2026-01-05", "13:00", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next(x for x in js if x["fecha"] == "2026-01-05")
    assert j["estado_jornada"] == "PARO"
    assert j["es_tarde"] == 0


# ─── 13. Legajo excluido ──────────────────────────────────────────────────────

def test_legajo_excluido(cfg_vacia):
    df = _df(("99", "2026-01-05", "07:00", "ENTRADA"),
             ("99", "2026-01-05", "14:00", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=set(), excluir_tardanza={"99"})
    j = next(x for x in js if x["fecha"] == "2026-01-05")
    assert j["estado_jornada"] == "EXCLUIDA"
    assert j["es_tarde"] == 0


# ─── 14. Asignación especial a las 05:00 ─────────────────────────────────────

def test_asignacion_especial(monkeypatch):
    asig = [{"legajo": "10", "desde": "2026-01-01", "hasta": "2026-12-31", "inicio": "05:00"}]
    monkeypatch.setattr("puntualidad_service.cargar_config", lambda: {})
    monkeypatch.setattr("puntualidad_service.cargar_feriados", lambda c: set())
    monkeypatch.setattr("puntualidad_service.cargar_dias_paro", lambda c: set())
    monkeypatch.setattr("puntualidad_service.cargar_asignaciones_especiales", lambda: asig)

    df = _df(("10", "2026-01-05", "05:07", "ENTRADA"),
             ("10", "2026-01-05", "12:00", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next(x for x in js if x["fecha"] == "2026-01-05")
    assert j["hora_programada"] == "05:00"
    assert j["estado_jornada"] == "TARDE"
    assert j["minutos_tarde"] == 7
    assert "Asignación especial" in j["observacion"]


# ─── 15. Horario fijo del departamento ───────────────────────────────────────

def test_horario_fijo(monkeypatch):
    cfg = {"horarios_fijos": {
        "redes": [{"desde": "2026-01-01", "hasta": "2026-12-31", "hora": "07:00"}]
    }}
    monkeypatch.setattr("puntualidad_service.cargar_config", lambda: cfg)
    monkeypatch.setattr("puntualidad_service.cargar_feriados", lambda c: set())
    monkeypatch.setattr("puntualidad_service.cargar_dias_paro", lambda c: set())
    monkeypatch.setattr("puntualidad_service.cargar_asignaciones_especiales", lambda: [])

    # Entrada a las 07:08 → 8 min tarde
    df = _df(("10", "2026-01-05", "07:08", "ENTRADA"),
             ("10", "2026-01-05", "14:00", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next(x for x in js if x["fecha"] == "2026-01-05")
    assert j["hora_programada"] == "07:00"
    assert j["estado_jornada"] == "TARDE"
    assert j["minutos_tarde"] == 8
    assert "Horario fijo" in j["observacion"]


# ─── 16. Cuadrilla inferida ───────────────────────────────────────────────────

def test_cuadrilla_inferida(cfg_vacia):
    # Varios empleados entran alrededor de las 05:00 → cuadrilla = 05:00
    # Empleado 20 entra a las 05:08 → 8 min tarde
    df = _df(
        ("11", "2026-01-05", "05:00", "ENTRADA", "redes", "Emp 11"),
        ("11", "2026-01-05", "12:00", "SALIDA",  "redes", "Emp 11"),
        ("12", "2026-01-05", "05:01", "ENTRADA", "redes", "Emp 12"),
        ("12", "2026-01-05", "12:00", "SALIDA",  "redes", "Emp 12"),
        ("13", "2026-01-05", "04:59", "ENTRADA", "redes", "Emp 13"),
        ("13", "2026-01-05", "12:00", "SALIDA",  "redes", "Emp 13"),
        ("20", "2026-01-05", "05:08", "ENTRADA", "redes", "Emp 20"),
        ("20", "2026-01-05", "12:00", "SALIDA",  "redes", "Emp 20"),
    )
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j20 = next(x for x in js if x["legajo"] == "20" and x["fecha"] == "2026-01-05")
    assert j20["hora_programada"] == "05:00"
    assert j20["estado_jornada"] == "TARDE"
    assert j20["minutos_tarde"] == 8
    assert "cuadrilla" in j20["observacion"].lower()


# ─── 17. Cinco tardanzas en un mes: NARANJA ──────────────────────────────────

def test_cinco_tardanzas_naranja():
    jornadas = [
        _jornada_manual(fecha=f"2026-01-{5+i:02d}", es_tarde=1, minutos_tarde=10,
                        estado_jornada="TARDE")
        for i in range(5)
    ]
    resumenes = resumir_por_mes(jornadas)
    assert len(resumenes) == 1
    assert resumenes[0]["cantidad_tardanzas"] == 5
    assert resumenes[0]["estado_mensual"] == "NARANJA"


# ─── 18. Tres tardanzas: AMARILLO ────────────────────────────────────────────

def test_tres_tardanzas_amarillo():
    jornadas = [
        _jornada_manual(fecha=f"2026-01-{5+i:02d}", es_tarde=1, minutos_tarde=8,
                        estado_jornada="TARDE")
        for i in range(3)
    ]
    resumenes = resumir_por_mes(jornadas)
    assert resumenes[0]["estado_mensual"] == "AMARILLO"


# ─── 19. Dos tardanzas: VERDE ────────────────────────────────────────────────

def test_dos_tardanzas_verde():
    jornadas = [
        _jornada_manual(fecha=f"2026-01-{5+i:02d}", es_tarde=1, minutos_tarde=6,
                        estado_jornada="TARDE")
        for i in range(2)
    ]
    resumenes = resumir_por_mes(jornadas)
    assert resumenes[0]["estado_mensual"] == "VERDE"


# ─── 20. Contador mensual vuelve a cero al mes siguiente ─────────────────────

def test_contador_vuelve_cero_mes_siguiente():
    # 5 tardanzas en enero → NARANJA
    # 0 tardanzas en febrero → VERDE
    jornadas_ene = [
        _jornada_manual(mes=1, fecha=f"2026-01-{5+i:02d}", es_tarde=1,
                        minutos_tarde=10, estado_jornada="TARDE")
        for i in range(5)
    ]
    jornadas_feb = [
        _jornada_manual(mes=2, fecha="2026-02-02", es_tarde=0, estado_jornada="PUNTUAL")
    ]
    resumenes = resumir_por_mes(jornadas_ene + jornadas_feb)
    r_ene = next(r for r in resumenes if r["mes"] == 1)
    r_feb = next(r for r in resumenes if r["mes"] == 2)
    assert r_ene["estado_mensual"] == "NARANJA"
    assert r_feb["estado_mensual"] == "VERDE"
    assert r_feb["cantidad_tardanzas"] == 0


# ─── 21. Mismo empleado en dos meses → dos filas ─────────────────────────────

def test_mismo_empleado_dos_meses():
    jornadas = [
        _jornada_manual(mes=1, fecha="2026-01-05", es_tarde=1,
                        minutos_tarde=6, estado_jornada="TARDE"),
        _jornada_manual(mes=2, fecha="2026-02-02", es_tarde=0,
                        estado_jornada="PUNTUAL"),
    ]
    resumenes = resumir_por_mes(jornadas)
    assert len(resumenes) == 2
    meses = {r["mes"] for r in resumenes}
    assert meses == {1, 2}


# ─── 22. Dos empleados de deptos distintos no se mezclan ─────────────────────

def test_deptos_distintos_no_se_mezclan():
    jornadas = [
        _jornada_manual(legajo="10", departamento="redes",
                        es_tarde=1, minutos_tarde=6, estado_jornada="TARDE"),
        _jornada_manual(legajo="20", departamento="administracion",
                        es_tarde=0, estado_jornada="PUNTUAL"),
    ]
    resumenes = resumir_por_mes(jornadas)
    assert len(resumenes) == 2
    deptos = {r["departamento"] for r in resumenes}
    assert deptos == {"redes", "administracion"}
    r_redes = next(r for r in resumenes if r["departamento"] == "redes")
    r_adm   = next(r for r in resumenes if r["departamento"] == "administracion")
    assert r_redes["cantidad_tardanzas"] == 1
    assert r_adm["cantidad_tardanzas"] == 0


# ─── 23. 10 tardanzas anuales: ADVERTENCIA_ANUAL ─────────────────────────────

def test_diez_tardanzas_advertencia_anual():
    assert obtener_estado_anual(10) == "ADVERTENCIA_ANUAL"
    assert obtener_estado_anual(12) == "ADVERTENCIA_ANUAL"


# ─── 24. 13 tardanzas anuales: ROJO ──────────────────────────────────────────

def test_trece_tardanzas_rojo():
    assert obtener_estado_anual(13) == "ROJO"
    assert obtener_estado_anual(20) == "ROJO"


# ─── 25. Prioridad visual: ROJO sobre NARANJA ────────────────────────────────

def test_prioridad_rojo_sobre_naranja():
    # 5 del mes (→NARANJA) pero 13 anuales (→ROJO): gana ROJO
    assert obtener_estado_visual(5, 13) == "ROJO"


# ─── 26. Prioridad visual: NARANJA sobre AMARILLO ────────────────────────────

def test_prioridad_naranja_sobre_amarillo():
    # 5 del mes (→NARANJA), 10 anuales (→ podría dar AMARILLO), gana NARANJA
    assert obtener_estado_visual(5, 10) == "NARANJA"


# ─── 27. Cambio de año: resultados separados ─────────────────────────────────

def test_cambio_de_ano():
    jornadas = [
        _jornada_manual(anio=2026, mes=12, fecha="2026-12-07",
                        es_tarde=1, minutos_tarde=8, estado_jornada="TARDE"),
        _jornada_manual(anio=2027, mes=1,  fecha="2027-01-05",
                        es_tarde=0, estado_jornada="PUNTUAL"),
    ]
    resumenes = resumir_por_mes(jornadas)
    r2026 = next(r for r in resumenes if r["anio"] == 2026)
    r2027 = next(r for r in resumenes if r["anio"] == 2027)
    assert r2026["cantidad_tardanzas"] == 1
    assert r2027["cantidad_tardanzas"] == 0


# ─── 28. DataFrame original no se modifica ────────────────────────────────────

def test_dataframe_original_no_modificado(cfg_vacia):
    df = _df(("10", "2026-01-05", "06:00", "ENTRADA"),
             ("10", "2026-01-05", "13:00", "SALIDA"))
    columnas_antes  = list(df.columns)
    registros_antes = df.to_dict("records")

    calcular_jornadas_puntualidad(df, feriados=set())

    assert list(df.columns) == columnas_antes
    assert df.to_dict("records") == registros_antes


# ─── 29. Formato de los campos devueltos ─────────────────────────────────────

def test_formato_campos_jornada(cfg_vacia):
    df = _df(("10", "2026-06-03", "06:08", "ENTRADA"),
             ("10", "2026-06-03", "13:00", "SALIDA"))
    js = calcular_jornadas_puntualidad(df, feriados=set(), archivo_origen="test.xlsx")
    j = next(x for x in js if x["fecha"] == "2026-06-03")

    assert j["fecha"] == "2026-06-03"
    assert j["anio"] == 2026
    assert j["mes"] == 6
    assert isinstance(j["legajo"], str)
    assert isinstance(j["minutos_tarde"], int)
    assert j["minutos_tarde"] >= 0
    assert j["es_tarde"] in (0, 1)
    assert j["hora_programada"] is None or ":" in j["hora_programada"]
    assert j["hora_entrada"] is None or ":" in j["hora_entrada"]
    assert j["origen"] == "CALCULO_AUTOMATICO"
    assert j["archivo_origen"] == "test.xlsx"
    assert len(j["procesado_en"]) == 19   # "YYYY-MM-DD HH:MM:SS"
    assert j["estado_jornada"] in {
        "PUNTUAL","TARDE","SIN_ENTRADA","EXCLUIDA",
        "FERIADO","FIN_DE_SEMANA","PARO","INCOMPLETA"
    }


# ─── 30. Cruce de madrugada imputable al día anterior ─────────────────────────

def test_madrugada_imputable_al_dia_anterior(cfg_vacia):
    """
    Par (02:00, 03:00) en madrugada del martes es atribuido al lunes.
    No debe aparecer como jornada independiente del martes.
    """
    df = _df(
        # Lunes: turno normal
        ("10", "2026-01-05", "06:00", "ENTRADA", "redes"),
        ("10", "2026-01-05", "20:00", "SALIDA",  "redes"),
        # Martes madrugada: debe atribuirse al lunes (ambos < 04:30, misma fecha)
        ("10", "2026-01-06", "02:00", "ENTRADA", "redes"),
        ("10", "2026-01-06", "03:00", "SALIDA",  "redes"),
    )
    js = calcular_jornadas_puntualidad(df, feriados=set())
    fechas = [j["fecha"] for j in js if j["legajo"] == "10"]

    # Lunes debe existir
    assert "2026-01-05" in fechas
    # Martes no debe tener jornada propia (el par fue atribuido al lunes)
    assert "2026-01-06" not in fechas


# ─── Tests de funciones puras de estado ──────────────────────────────────────

def test_obtener_estado_mensual_limites():
    assert obtener_estado_mensual(0) == "VERDE"
    assert obtener_estado_mensual(2) == "VERDE"
    assert obtener_estado_mensual(3) == "AMARILLO"
    assert obtener_estado_mensual(4) == "AMARILLO"
    assert obtener_estado_mensual(5) == "NARANJA"
    assert obtener_estado_mensual(9) == "NARANJA"


def test_obtener_estado_anual_limites():
    assert obtener_estado_anual(0)  == "NORMAL"
    assert obtener_estado_anual(9)  == "NORMAL"
    assert obtener_estado_anual(10) == "ADVERTENCIA_ANUAL"
    assert obtener_estado_anual(12) == "ADVERTENCIA_ANUAL"
    assert obtener_estado_anual(13) == "ROJO"


def test_obtener_estado_visual_todos_los_casos():
    assert obtener_estado_visual(0, 0)  == "VERDE"
    assert obtener_estado_visual(2, 9)  == "VERDE"
    assert obtener_estado_visual(3, 0)  == "AMARILLO"
    assert obtener_estado_visual(0, 10) == "AMARILLO"
    assert obtener_estado_visual(5, 0)  == "NARANJA"
    assert obtener_estado_visual(5, 9)  == "NARANJA"
    assert obtener_estado_visual(0, 13) == "ROJO"
    assert obtener_estado_visual(5, 13) == "ROJO"   # ROJO gana sobre NARANJA


# ─── normalizar_archivo_fichadas ─────────────────────────────────────────────

def test_normalizar_acepta_nombres_originales():
    df = pd.DataFrame([{
        "Nro. de usuario": "10",
        "Fecha/Hora":      pd.Timestamp("2026-01-05 06:00"),
        "Tipo de registro": "ENTRADA",
    }])
    resultado = normalizar_archivo_fichadas(df)
    assert "Legajo" in resultado.columns
    assert "FechaHora" in resultado.columns
    assert "Tipo" in resultado.columns


def test_normalizar_elimina_duplicados():
    df = pd.DataFrame([
        {"Legajo": "10", "FechaHora": pd.Timestamp("2026-01-05 06:00"), "Tipo": "ENTRADA"},
        {"Legajo": "10", "FechaHora": pd.Timestamp("2026-01-05 06:00"), "Tipo": "ENTRADA"},
    ])
    resultado = normalizar_archivo_fichadas(df)
    assert len(resultado) == 1


# ─── filtrar_periodo ──────────────────────────────────────────────────────────

def test_filtrar_periodo_inclusive():
    from datetime import date
    df = pd.DataFrame([
        {"FechaHora": pd.Timestamp("2026-01-01 06:00"), "Legajo": "10"},
        {"FechaHora": pd.Timestamp("2026-01-15 06:00"), "Legajo": "10"},
        {"FechaHora": pd.Timestamp("2026-02-01 06:00"), "Legajo": "10"},
    ])
    resultado = filtrar_periodo(df, "2026-01-01", "2026-01-15")
    assert len(resultado) == 2


def test_filtrar_periodo_fecha_invertida_lanza_error():
    df = pd.DataFrame([{"FechaHora": pd.Timestamp("2026-01-05 06:00"), "Legajo": "10"}])
    with pytest.raises(ValueError, match="fecha_desde"):
        filtrar_periodo(df, "2026-02-01", "2026-01-01")


# ─── incompleta + tarde ────────────────────────────────────────────────────────

def test_incompleta_con_tardanza(cfg_vacia):
    # ENTRADA a las 06:10 (4 min tarde), sin SALIDA → INCOMPLETA y es_tarde=1
    df = _df(("10", "2026-01-05", "06:10", "ENTRADA"))
    js = calcular_jornadas_puntualidad(df, feriados=set())
    j = next(x for x in js if x["fecha"] == "2026-01-05")
    assert j["estado_jornada"] == "INCOMPLETA"
    assert j["es_tarde"] == 1
    assert j["minutos_tarde"] == 10
    assert "Llegada tarde" in j["observacion"]


# ─── resumir_por_mes: días evaluados ─────────────────────────────────────────

def test_dias_evaluados_excluye_especiales():
    jornadas = [
        _jornada_manual(estado_jornada="PUNTUAL"),
        _jornada_manual(fecha="2026-01-06", estado_jornada="FERIADO",     es_tarde=0),
        _jornada_manual(fecha="2026-01-07", estado_jornada="FIN_DE_SEMANA", es_tarde=0),
        _jornada_manual(fecha="2026-01-08", estado_jornada="PARO",        es_tarde=0),
        _jornada_manual(fecha="2026-01-09", estado_jornada="SIN_ENTRADA", es_tarde=0),
        _jornada_manual(fecha="2026-01-12", estado_jornada="EXCLUIDA",    es_tarde=0),
        _jornada_manual(fecha="2026-01-13", estado_jornada="TARDE",
                        es_tarde=1, minutos_tarde=8),
        _jornada_manual(fecha="2026-01-14", estado_jornada="INCOMPLETA"),
    ]
    r = resumir_por_mes(jornadas)
    assert len(r) == 1
    assert r[0]["dias_evaluados"] == 3   # PUNTUAL + TARDE + INCOMPLETA
    assert r[0]["cantidad_tardanzas"] == 1
