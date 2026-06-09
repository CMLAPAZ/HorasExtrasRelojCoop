# -*- coding: utf-8 -*-
import pandas as pd
from datetime import datetime
# El import siguiente asume que ejecutarás pytest desde la raíz del proyecto
# y que procesador.py está en el PYTHONPATH o en la raíz.
import procesador as P

def _row(legajo, nombre, depto, fecha_hora, tipo):
    return {
        "Nro. de usuario": legajo,
        "Nombre": nombre,
        "Departamento": depto,
        "Fecha/Hora": fecha_hora,
        "Tipo de registro": tipo
    }

def test_comida_dia_habil_bloque_largo():
    # Día hábil: un solo tramo 06:00–14:00 (8h) -> con umbral_1=7h30, debería marcar 1 comida
    data = [
        _row("100","Juan","REDES","2025-09-01 06:00:00","ENTRADA"),
        _row("100","Juan","REDES","2025-09-01 14:00:00","SALIDA"),
    ]
    df = pd.DataFrame(data)
    res = P.procesar_fichadas(df, feriados=set())
    # _df_to_registros normaliza el departamento a minúsculas
    key = ("redes", "100", "Juan")
    por_dia = res[key]
    d = list(sorted(por_dia.keys()))[0]
    tot = por_dia[d]["totales"]
    assert tot["comida"] >= 1, f"Se esperaba al menos 1 comida, totales={tot}"

def test_fin_de_semana_franco_y_100():
    # Domingo con 5 horas -> todo al 100% y franco=1
    data = [
        _row("200","Ana","ADM","2025-09-07 08:00:00","ENTRADA"),  # domingo
        _row("200","Ana","ADM","2025-09-07 13:00:00","SALIDA"),
    ]
    df = pd.DataFrame(data)
    res = P.procesar_fichadas(df, feriados=set())
    # _df_to_registros normaliza el departamento a minúsculas
    key = ("adm", "200", "Ana")
    por_dia = res[key]
    d = list(sorted(por_dia.keys()))[0]
    tot = por_dia[d]["totales"]
    assert tot["franco"] == 1, f"Debe otorgar franco en domingo con >=4h al 100%, totales={tot}"
