# -*- coding: utf-8 -*-
from pathlib import Path

from pypdf import PdfReader

from puntualidad_reporte import generar_informe_puntualidad_pdf


def test_genera_pdf_con_resumen_y_detalle(tmp_path):
    resumenes = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
        "dias_evaluados": 20, "cantidad_tardanzas": 2, "minutos_tarde": 18,
    }]
    tardanzas = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
        "fecha": "2026-02-05", "hora_programada": "06:00", "hora_entrada": "06:08",
        "minutos_tarde": 8, "observacion": "Llegada tarde",
    }]
    salida = Path(tmp_path) / "informe.pdf"
    generar_informe_puntualidad_pdf(str(Path(__file__).parent), str(salida), 2026, 2, resumenes, tardanzas)
    assert salida.exists() and salida.stat().st_size > 1000
    texto = "\n".join(page.extract_text() or "" for page in PdfReader(str(salida)).pages)
    assert "Informe de llegadas tarde" in texto
    assert "Empleado Prueba" in texto
    assert "2026-02-05" in texto
