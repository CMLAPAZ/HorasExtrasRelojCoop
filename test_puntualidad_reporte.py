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


def test_pdf_muestra_seccion_alertas_con_naranja(tmp_path):
    resumenes = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Naranja",
        "dias_evaluados": 20, "cantidad_tardanzas": 5, "minutos_tarde": 40,
    }]
    tardanzas = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Naranja",
        "fecha": "2026-02-05", "hora_programada": "06:00", "hora_entrada": "06:08",
        "minutos_tarde": 8, "observacion": "Llegada tarde",
    }]
    salida = Path(tmp_path) / "informe.pdf"
    generar_informe_puntualidad_pdf(str(Path(__file__).parent), str(salida), 2026, 2, resumenes, tardanzas)
    texto = "\n".join(page.extract_text() or "" for page in PdfReader(str(salida)).pages)
    assert "Alertas" in texto
    assert "Empleado Naranja" in texto
    assert "NARANJA" in texto


def test_pdf_alertas_vacio_muestra_mensaje(tmp_path):
    resumenes = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Verde",
        "dias_evaluados": 20, "cantidad_tardanzas": 1, "minutos_tarde": 8,
    }]
    tardanzas = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Verde",
        "fecha": "2026-02-05", "hora_programada": "06:00", "hora_entrada": "06:08",
        "minutos_tarde": 8, "observacion": "Llegada tarde",
    }]
    salida = Path(tmp_path) / "informe.pdf"
    generar_informe_puntualidad_pdf(str(Path(__file__).parent), str(salida), 2026, 2, resumenes, tardanzas)
    texto = "\n".join(page.extract_text() or "" for page in PdfReader(str(salida)).pages)
    assert "Sin empleados en estado NARANJA o ROJO" in texto


def test_pdf_detalle_muestra_justificacion_y_motivo(tmp_path):
    resumenes = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
        "dias_evaluados": 20, "cantidad_tardanzas": 0, "minutos_tarde": 0,
    }]
    tardanzas = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
        "fecha": "2026-02-05", "hora_programada": "06:00", "hora_entrada": "06:08",
        "minutos_tarde": 8, "observacion": "Llegada tarde",
        "justificada": True, "motivo_justificacion": "Turno médico",
    }]
    salida = Path(tmp_path) / "informe.pdf"
    generar_informe_puntualidad_pdf(str(Path(__file__).parent), str(salida), 2026, 2, resumenes, tardanzas)
    texto = "\n".join(page.extract_text() or "" for page in PdfReader(str(salida)).pages)
    assert "JUSTIFICADA" in texto
    assert "Turno" in texto


def test_pdf_alertas_modo_anual_usa_obtener_estado_anual(tmp_path):
    resumenes = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Rojo",
        "dias_evaluados": 200, "cantidad_tardanzas": 13, "minutos_tarde": 100,
    }]
    tardanzas = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Rojo",
        "fecha": "2026-02-05", "hora_programada": "06:00", "hora_entrada": "06:08",
        "minutos_tarde": 8, "observacion": "Llegada tarde",
    }]
    salida = Path(tmp_path) / "informe.pdf"
    generar_informe_puntualidad_pdf(str(Path(__file__).parent), str(salida), 2026, None, resumenes, tardanzas)
    texto = "\n".join(page.extract_text() or "" for page in PdfReader(str(salida)).pages)
    assert "ROJO" in texto
    assert "Empleado Rojo" in texto


def test_pdf_total_por_mes_en_informe_de_rango(tmp_path):
    resumenes = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
        "dias_evaluados": 40, "cantidad_tardanzas": 3, "minutos_tarde": 20,
    }]
    tardanzas = [
        {"departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
         "fecha": "2026-01-05", "mes": 1, "hora_programada": "06:00", "hora_entrada": "06:08",
         "minutos_tarde": 8, "observacion": "Llegada tarde"},
        {"departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
         "fecha": "2026-02-10", "mes": 2, "hora_programada": "06:00", "hora_entrada": "06:08",
         "minutos_tarde": 8, "observacion": "Llegada tarde"},
        {"departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
         "fecha": "2026-02-12", "mes": 2, "hora_programada": "06:00", "hora_entrada": "06:08",
         "minutos_tarde": 4, "observacion": "Llegada tarde",
         "justificada": True, "motivo_justificacion": "Turno médico"},
    ]
    salida = Path(tmp_path) / "informe.pdf"
    generar_informe_puntualidad_pdf(
        str(Path(__file__).parent), str(salida), 2026, 1, resumenes, tardanzas, mes_hasta=2
    )
    texto = "\n".join(page.extract_text() or "" for page in PdfReader(str(salida)).pages)
    assert "Total de tardanzas por mes" in texto
    assert "Enero: 1 tardanzas" in texto
    assert "Febrero: 1 tardanzas" in texto  # la justificada de febrero no cuenta
    assert "Total del periodo: 2 tardanzas" in texto


def test_pdf_total_general_del_periodo_en_informe_de_un_solo_mes(tmp_path):
    resumenes = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
        "dias_evaluados": 20, "cantidad_tardanzas": 2, "minutos_tarde": 16,
    }]
    tardanzas = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
        "fecha": "2026-02-05", "mes": 2, "hora_programada": "06:00", "hora_entrada": "06:08",
        "minutos_tarde": 8, "observacion": "Llegada tarde",
    }]
    salida = Path(tmp_path) / "informe.pdf"
    generar_informe_puntualidad_pdf(str(Path(__file__).parent), str(salida), 2026, 2, resumenes, tardanzas)
    texto = "\n".join(page.extract_text() or "" for page in PdfReader(str(salida)).pages)
    assert "Total de tardanzas del periodo: 2" in texto


def test_pdf_sin_total_por_mes_en_informe_de_un_solo_mes(tmp_path):
    resumenes = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
        "dias_evaluados": 20, "cantidad_tardanzas": 1, "minutos_tarde": 8,
    }]
    tardanzas = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
        "fecha": "2026-02-05", "mes": 2, "hora_programada": "06:00", "hora_entrada": "06:08",
        "minutos_tarde": 8, "observacion": "Llegada tarde",
    }]
    salida = Path(tmp_path) / "informe.pdf"
    generar_informe_puntualidad_pdf(str(Path(__file__).parent), str(salida), 2026, 2, resumenes, tardanzas)
    texto = "\n".join(page.extract_text() or "" for page in PdfReader(str(salida)).pages)
    assert "Total de tardanzas por mes" not in texto


def test_pdf_total_por_departamento_cuando_hay_mas_de_uno(tmp_path):
    resumenes = [
        {"departamento": "redes", "legajo": "10", "nombre": "Empleado Redes",
         "dias_evaluados": 20, "cantidad_tardanzas": 2, "minutos_tarde": 16},
        {"departamento": "administracion", "legajo": "20", "nombre": "Empleado Admin",
         "dias_evaluados": 20, "cantidad_tardanzas": 1, "minutos_tarde": 8},
    ]
    tardanzas = [
        {"departamento": "redes", "legajo": "10", "nombre": "Empleado Redes",
         "fecha": "2026-02-03", "mes": 2, "hora_programada": "06:00", "hora_entrada": "06:08",
         "minutos_tarde": 8, "observacion": "Llegada tarde"},
        {"departamento": "redes", "legajo": "10", "nombre": "Empleado Redes",
         "fecha": "2026-02-04", "mes": 2, "hora_programada": "06:00", "hora_entrada": "06:08",
         "minutos_tarde": 8, "observacion": "Llegada tarde"},
        {"departamento": "administracion", "legajo": "20", "nombre": "Empleado Admin",
         "fecha": "2026-02-05", "mes": 2, "hora_programada": "06:00", "hora_entrada": "06:08",
         "minutos_tarde": 8, "observacion": "Llegada tarde"},
    ]
    salida = Path(tmp_path) / "informe.pdf"
    generar_informe_puntualidad_pdf(str(Path(__file__).parent), str(salida), 2026, 2, resumenes, tardanzas)
    texto = "\n".join(page.extract_text() or "" for page in PdfReader(str(salida)).pages)
    assert "Total de tardanzas por departamento" in texto
    assert "REDES: 2 tardanzas" in texto
    assert "ADMINISTRACION: 1 tardanzas" in texto
    # La tabla resumen va separada por departamento, nunca mezclada en una
    # sola tabla con columna Depto.
    assert "Depto." not in texto
    pos_redes = texto.index("REDES")
    pos_admin = texto.index("ADMINISTRACION")
    pos_empleado_redes = texto.index("Empleado Redes")
    pos_empleado_admin = texto.index("Empleado Admin")
    assert pos_redes < pos_empleado_redes
    assert pos_admin < pos_empleado_admin


def test_pdf_sin_total_por_departamento_si_hay_uno_solo(tmp_path):
    resumenes = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
        "dias_evaluados": 20, "cantidad_tardanzas": 1, "minutos_tarde": 8,
    }]
    tardanzas = [{
        "departamento": "redes", "legajo": "10", "nombre": "Empleado Prueba",
        "fecha": "2026-02-05", "mes": 2, "hora_programada": "06:00", "hora_entrada": "06:08",
        "minutos_tarde": 8, "observacion": "Llegada tarde",
    }]
    salida = Path(tmp_path) / "informe.pdf"
    generar_informe_puntualidad_pdf(str(Path(__file__).parent), str(salida), 2026, 2, resumenes, tardanzas)
    texto = "\n".join(page.extract_text() or "" for page in PdfReader(str(salida)).pages)
    assert "Total de tardanzas por departamento" not in texto
