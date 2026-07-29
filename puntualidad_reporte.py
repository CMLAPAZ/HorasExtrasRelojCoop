# -*- coding: utf-8 -*-
"""Generacion PDF de informes de llegadas tarde."""
import os
from datetime import datetime

from fpdf import FPDF

from puntualidad_service import obtener_estado_mensual, obtener_estado_anual


MESES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def _font_paths(base_dir):
    carpeta = os.path.join(base_dir, "recursos", "fonts")
    return (
        os.path.join(carpeta, "DejaVuSans.ttf"),
        os.path.join(carpeta, "DejaVuSans-Bold.ttf"),
    )


class _PDFPuntualidad(FPDF):
    def __init__(self, base_dir, titulo):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.titulo = titulo
        self.set_auto_page_break(auto=True, margin=14)
        regular, bold = _font_paths(base_dir)
        self.familia = "Helvetica"
        if os.path.exists(regular) and os.path.exists(bold):
            self.add_font("DejaVu", "", regular)
            self.add_font("DejaVu", "B", bold)
            self.familia = "DejaVu"

    def header(self):
        self.set_font(self.familia, "B", 13)
        self.cell(0, 8, self.titulo, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font(self.familia, "", 8)
        self.cell(
            0, 5, f"Generado: {datetime.now():%d/%m/%Y %H:%M}",
            align="C", new_x="LMARGIN", new_y="NEXT",
        )
        self.ln(3)

    def footer(self):
        self.set_y(-10)
        self.set_font(self.familia, "", 7)
        self.cell(0, 5, f"Pagina {self.page_no()}", align="C")


def generar_informe_puntualidad_pdf(base_dir, ruta_salida, anio, mes, resumenes, tardanzas,
                                    mes_hasta=None):
    """Genera un PDF mensual (mes int) o anual (mes None)."""
    if mes is None:
        periodo = f"Acumulado anual {anio}"
    elif mes_hasta is not None:
        periodo = f"{MESES[int(mes)]} a {MESES[int(mes_hasta)]} {anio}"
    else:
        periodo = f"{MESES[int(mes)]} {anio}"
    pdf = _PDFPuntualidad(base_dir, f"Informe de llegadas tarde - {periodo}")
    pdf.add_page()
    fam = pdf.familia

    # Seccion de alertas: empleados en NARANJA (5+ tardanzas/mes) o ROJO
    # (13+ tardanzas/anio). El estado se recalcula con las funciones puras
    # a partir de cantidad_tardanzas (ya neta de justificadas) en vez de
    # leer "estado_mensual" del dict, porque en modo anual/rango esa clave
    # no existe en los resumenes agregados.
    es_periodo_agregado = mes is None or mes_hasta is not None
    alertas = []
    for r in resumenes:
        cant = int(r.get("cantidad_tardanzas") or 0)
        estado = obtener_estado_anual(cant) if es_periodo_agregado else obtener_estado_mensual(cant)
        if estado in ("NARANJA", "ROJO"):
            alertas.append((r, estado))
    alertas.sort(key=lambda par: (par[1] != "ROJO", -int(par[0].get("cantidad_tardanzas") or 0)))

    pdf.set_font(fam, "B", 10)
    pdf.cell(0, 7, "Alertas del periodo (NARANJA / ROJO)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(fam, "", 8)
    if not alertas:
        pdf.cell(0, 6, "Sin empleados en estado NARANJA o ROJO en este periodo.",
                 new_x="LMARGIN", new_y="NEXT")
    else:
        for r, estado in alertas:
            cant = int(r.get("cantidad_tardanzas") or 0)
            linea = (f"- {r['nombre']} (Legajo {r['legajo']}, "
                     f"{str(r['departamento']).upper()}): {estado} - {cant} tardanzas")
            pdf.cell(0, 5.5, linea[:110], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font(fam, "B", 9)
    anchos = [23, 18, 76, 22, 23, 24]
    titulos = ["Depto.", "Legajo", "Empleado", "Dias eval.", "Tardanzas", "Minutos"]
    for ancho, titulo in zip(anchos, titulos):
        pdf.cell(ancho, 7, titulo, border=1, align="C")
    pdf.ln()
    pdf.set_font(fam, "", 8)
    for r in resumenes:
        valores = [
            str(r["departamento"]).upper(), str(r["legajo"]), str(r["nombre"]),
            str(r["dias_evaluados"]), str(r["cantidad_tardanzas"]), str(r["minutos_tarde"]),
        ]
        for i, (ancho, valor) in enumerate(zip(anchos, valores)):
            pdf.cell(ancho, 6, valor[:38], border=1, align="L" if i == 2 else "C")
        pdf.ln()

    por_empleado = {}
    for t in tardanzas:
        clave = (str(t["departamento"]), str(t["legajo"]), str(t["nombre"]))
        por_empleado.setdefault(clave, []).append(t)

    for (depto, legajo, nombre), filas in por_empleado.items():
        pdf.ln(5)
        if pdf.get_y() > 245:
            pdf.add_page()
        pdf.set_font(fam, "B", 9)
        pdf.cell(0, 6, f"{nombre} - Legajo {legajo} - {depto.upper()}", new_x="LMARGIN", new_y="NEXT")
        cols = [25, 22, 22, 18, 101]
        pdf.set_font(fam, "B", 8)
        for ancho, titulo in zip(cols, ["Fecha", "Programada", "Entrada", "Min.", "Observacion"]):
            pdf.cell(ancho, 6, titulo, border=1, align="C")
        pdf.ln()
        pdf.set_font(fam, "", 7.5)
        for t in filas:
            if t.get("justificada"):
                motivo = str(t.get("motivo_justificacion") or "").strip()
                obs = f"JUSTIFICADA - {motivo}" if motivo else "JUSTIFICADA"
            else:
                obs = str(t.get("observacion") or "Llegada tarde")
            valores = [t["fecha"], t.get("hora_programada") or "", t.get("hora_entrada") or "", str(t["minutos_tarde"]), obs]
            for i, (ancho, valor) in enumerate(zip(cols, valores)):
                pdf.cell(ancho, 5.5, str(valor)[:70], border=1, align="L" if i == 4 else "C")
            pdf.ln()

    os.makedirs(os.path.dirname(os.path.abspath(ruta_salida)), exist_ok=True)
    pdf.output(ruta_salida)
    return ruta_salida
