# -*- coding: utf-8 -*-
from fpdf import FPDF
from datetime import timedelta
import os

# --- Utilidades robustas ---
def _td_from_any(x):
    """Convierte a timedelta: timedelta | 'HH:MM:SS' | número (segundos) | vacío."""
    if isinstance(x, timedelta):
        return x
    if isinstance(x, (int, float)):
        return timedelta(seconds=float(x))
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return timedelta(0)
        parts = s.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return timedelta(hours=int(h), minutes=int(m), seconds=int(float(s)))
    return timedelta(0)

def formato_horas(td):
    td = _td_from_any(td)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"

def _round_to_hour(td):
    """Redondea a horas enteras (≥30' hacia arriba)."""
    td = _td_from_any(td)
    if td <= timedelta(0):
        return timedelta(0)
    minutes = td.total_seconds() / 60.0
    hours = int(minutes // 60)
    rem = minutes - hours * 60
    if rem >= 30:
        hours += 1
    return timedelta(hours=hours)

# ---------------- PDF ----------------
class PDFGeneral(FPDF):
    def __init__(self):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.set_auto_page_break(auto=True, margin=15)

        # 👉 Ruta fija donde están las fuentes
        base_path = r"C:\Users\USUARIO\OneDrive\Apps\CM_HorasExtras\dejavu-fonts-ttf-2.37\dejavu-fonts-ttf-2.37\ttf"

        # 👉 Registrar las variantes de DejaVu
        self.add_font("DejaVu", "", os.path.join(base_path, "DejaVuSans.ttf"), uni=True)
        self.add_font("DejaVu", "B", os.path.join(base_path, "DejaVuSans-Bold.ttf"), uni=True)
        self.add_font("DejaVu", "I", os.path.join(base_path, "DejaVuSans-Oblique.ttf"), uni=True)

        # Fuente por defecto
        self.set_font("DejaVu", "", 7)

        self.titulo = ""
        self.columnas = []
        self.anchos = []

    def header(self):
        self.set_font("DejaVu", "B", 12)
        self.cell(0, 10, self.titulo, ln=1, align="C")
        self.ln(3)

    def footer(self):
        self.set_y(-15)
        self.set_font("DejaVu", "I", 8)
        self.cell(0, 10, f"Página {self.page_no()}", 0, 0, "L")
        self.set_y(-15)
        self.set_x(-70)
        self.set_font("DejaVu", "I", 7)
        self.cell(60, 10, "Realizado por CM_Carola", 0, 0, "R")

    def encabezado_empleado(self, legajo, nombre="", departamento=""):
        self.set_font("DejaVu", "B", 10)
        texto = f"Legajo: {legajo}"
        if nombre:
            texto += f"   |   Nombre: {nombre}"
        if departamento:
            texto += f"   |   Departamento: {departamento}"
        self.cell(0, 8, texto, ln=1)
        self.ln(1)

    def _titulos_columnas(self, columnas, anchos):
        self.set_font("DejaVu", "B", 8)
        for col, ancho in zip(columnas, anchos):
            self.cell(ancho, 6, col, 1, 0, 'C')
        self.ln()
        self.set_font("DejaVu", "", 7)

    def _decorar_observacion(self, texto):
        """Agrega símbolos bonitos a la observación según el caso."""
        if not texto:
            return ""
        t = texto.lower()
        if "break" in t:
            return f"✌ {texto}"
        if "tarde" in t:
            return f"☹ {texto}"
        if "temprano" in t or "salida anticipada" in t:
            return f"☺ {texto}"
        if "error" in t or "inconsistencia" in t:
            return f"✘ {texto}"
        return texto

    def tabla_registros(self, registros):
        columnas = ["Fecha", "Entrada", "Salida", "Normales", "50%", "100%", "COMIDA", "FRANCO", "Tarde", "Observaciones"]
        anchos   = [16,      16,        16,        18,        16,    16,     12,        12,       10,      48]
        self.columnas = columnas
        self.anchos = anchos

        self._titulos_columnas(columnas, anchos)

        # Inicialización correcta
        total_normal = timedelta(0)
        total_50     = timedelta(0)
        total_100    = timedelta(0)
        total_tarde  = 0
        total_franco = 0
        total_comida = 0

        for r in registros:
            normales  = _td_from_any(r.get("Normales", "00:00:00"))
            extras50  = _td_from_any(r.get("50%", "00:00:00"))
            extras100 = _td_from_any(r.get("100%", "00:00:00"))
            obs = self._decorar_observacion(r.get("Observaciones", ""))

            self.cell(anchos[0], 6, r.get("Fecha", ""), 1)
            self.cell(anchos[1], 6, str(r.get("Entrada", "")), 1)
            self.cell(anchos[2], 6, str(r.get("Salida", "")), 1)
            self.cell(anchos[3], 6, formato_horas(normales), 1)
            self.cell(anchos[4], 6, formato_horas(extras50), 1)
            self.cell(anchos[5], 6, formato_horas(extras100), 1)
            self.cell(anchos[6], 6, str(int(r.get("COMIDA", 0))), 1)
            self.cell(anchos[7], 6, str(int(r.get("FRANCO", 0))), 1)
            self.cell(anchos[8], 6, str(int(r.get("Tarde", 0))), 1)
            self.cell(anchos[9], 6, obs, 1)
            self.ln()

            # Acumular totales
            total_normal += normales
            total_50     += extras50
            total_100    += extras100
            total_tarde  += int(r.get("Tarde", 0))
            total_franco += int(r.get("FRANCO", 0))
            total_comida += int(r.get("COMIDA", 0))

        # Totales
        self.set_font("DejaVu", "B", 8)
        self.cell(0, 6, "Totales del mes:", ln=1)
        self.cell(0, 6, f"Horas Normales: {formato_horas(total_normal)}", ln=1)
        self.cell(0, 6, f"Horas 50%: {formato_horas(_round_to_hour(total_50))}", ln=1)
        self.cell(0, 6, f"Horas 100%: {formato_horas(_round_to_hour(total_100))}", ln=1)
        self.cell(0, 6, f"Comidas: {total_comida}", ln=1)
        self.cell(0, 6, f"Francos: {total_franco}", ln=1)
        self.cell(0, 6, f"Llegadas tarde: {total_tarde}", ln=1)
        self.ln(4)

# ------------ Funciones de generación ----------------
def generar_pdf_general(data, mes, salida="reporte_fichadas.pdf"):
    pdf = PDFGeneral()
    pdf.titulo = f"Informe de Fichadas - {mes}"
    for empleado in data:
        pdf.add_page()
        legajo = empleado.get("legajo", "")
        nombre = empleado.get("nombre", "")
        departamento = empleado.get("departamento", "")
        pdf.encabezado_empleado(legajo, nombre, departamento)
        pdf.tabla_registros(empleado.get("registros", []))
    pdf.output(salida)
    return os.path.abspath(salida)

def generar_pdf_resumen(data, mes, salida="reporte_resumen.pdf"):
    pdf = PDFGeneral()
    pdf.titulo = f"Resumen de Totales - {mes}"
    pdf.columnas = ["Legajo", "Nombre", "Normales", "50%", "100%", "COMIDA", "FRANCO", "Tarde"]
    pdf.anchos   = [20,       40,        20,         20,    20,     15,        15,       15]

    pdf.add_page()
    pdf.set_font("DejaVu", "B", 8)
    for col, ancho in zip(pdf.columnas, pdf.anchos):
        pdf.cell(ancho, 7, col, 1, 0, 'C')
    pdf.ln()

    total_normal = timedelta(0)
    total_50     = timedelta(0)
    total_100    = timedelta(0)
    total_tarde  = 0
    total_franco = 0
    total_comida = 0

    for emp in data:
        legajo = emp.get("legajo", "")
        nombre = emp.get("nombre", "")
        registros = emp.get("registros", [])

        emp_normal = timedelta(0)
        emp_50     = timedelta(0)
        emp_100    = timedelta(0)
        emp_tarde  = 0
        emp_franco = 0
        emp_comida = 0

        for r in registros:
            emp_normal += _td_from_any(r.get("Normales", "00:00:00"))
            emp_50     += _td_from_any(r.get("50%", "00:00:00"))
            emp_100    += _td_from_any(r.get("100%", "00:00:00"))
            emp_comida += int(r.get("COMIDA", 0))
            emp_franco += int(r.get("FRANCO", 0))
            emp_tarde  += int(r.get("Tarde", 0))

        total_normal += emp_normal
        total_50     += emp_50
        total_100    += emp_100
        total_comida += emp_comida
        total_franco += emp_franco
        total_tarde  += emp_tarde

        pdf.set_font("DejaVu", "", 7)
        fila = [
            str(legajo), nombre,
            formato_horas(emp_normal),
            formato_horas(_round_to_hour(emp_50)),
            formato_horas(_round_to_hour(emp_100)),
            str(emp_comida),
            str(emp_franco),
            str(emp_tarde)
        ]
        for dato, ancho in zip(fila, pdf.anchos):
            pdf.cell(ancho, 6, dato, 1)
        pdf.ln()

    # Fila de totales
    pdf.set_font("DejaVu", "B", 8)
    pdf.cell(pdf.anchos[0] + pdf.anchos[1], 7, "TOTALES", 1, 0, "R")
    pdf.cell(pdf.anchos[2], 7, formato_horas(total_normal), 1)
    pdf.cell(pdf.anchos[3], 7, formato_horas(_round_to_hour(total_50)), 1)
    pdf.cell(pdf.anchos[4], 7, formato_horas(_round_to_hour(total_100)), 1)
    pdf.cell(pdf.anchos[5], 7, str(total_comida), 1)
    pdf.cell(pdf.anchos[6], 7, str(total_franco), 1)
    pdf.cell(pdf.anchos[7], 7, str(total_tarde), 1)
    pdf.ln()

    pdf.output(salida)
    return os.path.abspath(salida)
