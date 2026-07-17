# -*- coding: utf-8 -*-
"""Los legajos de Ingenieros no ingresan al procesamiento biométrico."""
import pandas as pd

import procesador


def test_gatti_y_mancioni_se_excluyen_antes_de_calcular():
    df = pd.DataFrame([
        {"Nro. de usuario": 100, "Nombre": "MANCIONI, Martin", "Departamento": "Redes",
         "Fecha/Hora": "2026-07-01 06:00:00", "Tipo de registro": "ENTRADA"},
        {"Nro. de usuario": 100, "Nombre": "MANCIONI, Martin", "Departamento": "Redes",
         "Fecha/Hora": "2026-07-01 13:00:00", "Tipo de registro": "SALIDA"},
        {"Nro. de usuario": "101", "Nombre": "GATTI, Marcelo", "Departamento": "Redes",
         "Fecha/Hora": "2026-07-01 06:00:00", "Tipo de registro": "ENTRADA"},
        {"Nro. de usuario": "101", "Nombre": "GATTI, Marcelo", "Departamento": "Redes",
         "Fecha/Hora": "2026-07-01 13:00:00", "Tipo de registro": "SALIDA"},
        {"Nro. de usuario": 102, "Nombre": "SOTO, Karen", "Departamento": "Redes",
         "Fecha/Hora": "2026-07-01 06:00:00", "Tipo de registro": "ENTRADA"},
        {"Nro. de usuario": 102, "Nombre": "SOTO, Karen", "Departamento": "Redes",
         "Fecha/Hora": "2026-07-01 13:00:00", "Tipo de registro": "SALIDA"},
    ])

    registros = procesador._df_to_registros(df)
    legajos = {str(r[1]).removesuffix(".0") for r in registros}
    assert legajos == {"102"}

    resultados = procesador.procesar_fichadas(df)
    legajos_resultado = {str(k[1]).removesuffix(".0") for k in resultados}
    assert legajos_resultado == {"102"}
