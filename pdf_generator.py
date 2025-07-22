from fpdf import FPDF
from datetime import timedelta
import os

def formato_horas(td):
    if isinstance(td, timedelta):
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return str(td)

class PDFGeneral(FPDF):
    def __init__(self):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.set_auto_page_break(auto=True, margin=15)
        self.titulo = ""
        self.columnas = []
        self.anchos = []

    def header(self):
        self.set_font("Arial", "B", 12)
        self.cell(0, 10, self.titulo, ln=1, align="C")
        self.ln(3)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.cell(0, 10, f"Página {self.page_no()}", 0, 0, "L")
        self.set_y(-15)
        self.set_x(-70)
        self.set_font("Arial", "I", 7)
        self.cell(60, 10, "Realizado por CM_Carola", 0, 0, "R")

    def encabezado_empleado(self, legajo, nombre="", departamento=""):
        self.set_font("Arial", "B", 10)
        texto = f"Legajo: {legajo}"
        if nombre:
            texto += f"   |   Nombre: {nombre}"
        if departamento:
            texto += f"   |   Departamento: {departamento}"
        self.multi_cell(0, 8, texto)
        self.ln(2)

    def tabla_registros(self, registros):
        columnas = ["Fecha", "Entrada", "Salida", "Normales", "50%", "100%", "Tarde", "FRANCO", "COMIDA", "Observaciones"]
        anchos = [16, 16, 16, 18, 16, 16, 10, 12, 12, 48]
        self.columnas = columnas
        self.anchos = anchos

        self.set_font("Arial", "B", 8)
        for col, ancho in zip(columnas, anchos):
            self.cell(ancho, 6, col, 1, 0, 'C')
        self.ln()

        total_normal = timedelta()
        total_50 = timedelta()
        total_100 = timedelta()
        total_tarde = 0
        total_franco = 0
        total_comida = 0

        # --- Agrupa por día para saber cuál es la última fila de cada día ---
        registros_por_fecha = {}
        for r in registros:
            registros_por_fecha.setdefault(r["Fecha"], []).append(r)

        for fecha, registros_dia in registros_por_fecha.items():
            n = len(registros_dia)
            suma_normales = timedelta()
            suma_50 = timedelta()
            suma_100 = timedelta()
            suma_tarde = 0
            suma_franco = 0
            suma_comida = 0

            for idx, r in enumerate(registros_dia):
                es_ultima = idx == n - 1
                normales = r.get("Normales", timedelta())
                extra_50 = r.get("50%", timedelta())
                extra_100 = r.get("100%", timedelta())
                tarde = r.get("Tarde", 0)
                franco = r.get("FRANCO", 0)
                comida = r.get("COMIDA", 0)
                obs = r.get("Observaciones", "")

                # Acumula para mostrar parciales por tramo
                suma_normales += normales if not es_ultima else timedelta(0)
                suma_50 += extra_50 if not es_ultima else timedelta(0)
                suma_100 += extra_100 if not es_ultima else timedelta(0)
                suma_tarde += tarde if not es_ultima else 0
                suma_franco += franco if not es_ultima else 0
                suma_comida += comida if not es_ultima else 0

                if es_ultima:
                    # Última fila del día en NEGRITA con TOTALES de ese día
                    self.set_font("Arial", "B", 7)
                    normales_totales = suma_normales + normales
                    extra_50_totales = suma_50 + extra_50
                    extra_100_totales = suma_100 + extra_100
                    tarde_total = suma_tarde + tarde
                    franco_total = suma_franco + franco
                    comida_total = suma_comida + comida
                else:
                    self.set_font("Arial", "", 7)
                    normales_totales = normales
                    extra_50_totales = extra_50
                    extra_100_totales = extra_100
                    tarde_total = tarde
                    franco_total = franco
                    comida_total = comida

                self.cell(anchos[0], 6, r["Fecha"], 1)
                self.cell(anchos[1], 6, r["Entrada"], 1)
                self.cell(anchos[2], 6, r["Salida"], 1)
                self.cell(anchos[3], 6, formato_horas(normales_totales), 1)
                self.cell(anchos[4], 6, formato_horas(extra_50_totales), 1)
                self.cell(anchos[5], 6, formato_horas(extra_100_totales), 1)
                self.cell(anchos[6], 6, str(tarde_total), 1)
                self.cell(anchos[7], 6, str(franco_total), 1)
                self.cell(anchos[8], 6, str(comida_total), 1)
                self.cell(anchos[9], 6, obs if es_ultima else "", 1)
                self.ln()

                # Sumar a totales generales SOLO en la última fila del día
                if es_ultima:
                    total_normal += normales_totales
                    total_50 += extra_50_totales
                    total_100 += extra_100_totales
                    total_tarde += tarde_total
                    total_franco += franco_total
                    total_comida += comida_total

        self.set_font("Arial", "B", 8)
        self.cell(0, 6, "Totales del mes:", ln=1)
        self.cell(0, 6, f"Horas Normales: {formato_horas(total_normal)}", ln=1)
        self.cell(0, 6, f"Horas 50%: {formato_horas(total_50)}", ln=1)
        self.cell(0, 6, f"Horas 100%: {formato_horas(total_100)}", ln=1)
        self.cell(0, 6, f"Llegadas tarde: {total_tarde}", ln=1)
        self.cell(0, 6, f"Francos: {total_franco}", ln=1)
        self.cell(0, 6, f"Comidas: {total_comida}", ln=1)
        self.ln(4)

def generar_pdf_general(data, mes, salida="reporte_fichadas.pdf"):
    pdf = PDFGeneral()
    pdf.titulo = f"Informe de Fichadas - {mes}"

    for empleado in data:
        pdf.add_page()
        legajo = empleado["legajo"]
        nombre = empleado.get("nombre", "")
        departamento = empleado.get("departamento", "")
        pdf.encabezado_empleado(legajo, nombre, departamento)
        pdf.tabla_registros(empleado["registros"])

    pdf.output(salida)
    return os.path.abspath(salida)

def generar_pdf_resumen(data, mes, salida="reporte_resumen.pdf"):
    pdf = PDFGeneral()
    pdf.titulo = f"Resumen de Totales - {mes}"
    pdf.columnas = ["Legajo", "Nombre", "Normales", "50%", "100%", "Tarde", "FRANCO", "COMIDA"]
    pdf.anchos = [20, 40, 20, 20, 20, 15, 15, 15]

    pdf.add_page()

    # Encabezado de columnas
    pdf.set_font("Arial", "B", 8)
    for col, ancho in zip(pdf.columnas, pdf.anchos):
        pdf.cell(ancho, 7, col, 1, 0, 'C')
    pdf.ln()

    # Acumuladores de totales
    total_normal = total_50 = total_100 = timedelta()
    total_tarde = total_franco = total_comida = 0

    for emp in data:
        legajo = emp.get("legajo", "")
        nombre = emp.get("nombre", "")
        registros = emp.get("registros", [])

        emp_normal = emp_50 = emp_100 = timedelta()
        emp_tarde = emp_franco = emp_comida = 0

        for r in registros:
            emp_normal += r.get("Normales", timedelta())
            emp_50 += r.get("50%", timedelta())
            emp_100 += r.get("100%", timedelta())
            emp_tarde += r.get("Tarde", 0)
            emp_franco += r.get("FRANCO", 0)
            emp_comida += r.get("COMIDA", 0)

        total_normal += emp_normal
        total_50 += emp_50
        total_100 += emp_100
        total_tarde += emp_tarde
        total_franco += emp_franco
        total_comida += emp_comida

        pdf.set_font("Arial", "", 7)
        fila = [
            str(legajo), nombre,
            formato_horas(emp_normal),
            formato_horas(emp_50),
            formato_horas(emp_100),
            str(emp_tarde),
            str(emp_franco),
            str(emp_comida)
        ]
        for dato, ancho in zip(fila, pdf.anchos):
            pdf.cell(ancho, 6, dato, 1)
        pdf.ln()

    # Fila de totales al final
    pdf.set_font("Arial", "B", 8)
    pdf.cell(pdf.anchos[0] + pdf.anchos[1], 7, "TOTALES", 1, 0, "R")
    pdf.cell(pdf.anchos[2], 7, formato_horas(total_normal), 1)
    pdf.cell(pdf.anchos[3], 7, formato_horas(total_50), 1)
    pdf.cell(pdf.anchos[4], 7, formato_horas(total_100), 1)
    pdf.cell(pdf.anchos[5], 7, str(total_tarde), 1)
    pdf.cell(pdf.anchos[6], 7, str(total_franco), 1)
    pdf.cell(pdf.anchos[7], 7, str(total_comida), 1)
    pdf.ln()

    pdf.output(salida)
    return os.path.abspath(salida)
