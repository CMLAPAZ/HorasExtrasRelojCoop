# -*- coding: utf-8 -*-
from fpdf import FPDF
from datetime import timedelta, datetime
import os

# --- Utilidades robustas ---
def _td_from_any(x):
    """Convierte a timedelta: timedelta | 'HH:MM:SS' | número | vacío."""
    if isinstance(x, timedelta):
        return x
    if isinstance(x, (int, float)):
        return timedelta(seconds=float(x))
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return timedelta(0)
        # Formato HH:MM:SS
        try:
            h, m, s2 = s.split(":")
            return timedelta(hours=int(h), minutes=int(m), seconds=int(float(s2)))
        except Exception:
            pass
        # Segundos sueltos
        try:
            return timedelta(seconds=float(s))
        except Exception:
            return timedelta(0)
    return timedelta(0)

def formato_horas(td):
    if not isinstance(td, timedelta):
        td = _td_from_any(td)
    total_seg = int(td.total_seconds())
    if total_seg < 0:
        total_seg = 0
    h = total_seg // 3600
    m = (total_seg % 3600) // 60
    s = total_seg % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def _round_to_hour(td):
    if not isinstance(td, timedelta):
        td = _td_from_any(td)
    if td <= timedelta(0):
        return timedelta(0)
    total_min = td.total_seconds() / 60.0
    horas = int(total_min // 60)
    resto = total_min - horas * 60
    if resto >= 30:
        horas += 1
    return timedelta(hours=horas)

def _parse_fecha(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None

def _resource_path(*relative):
    base = getattr(os, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *relative)

# ------------------ Clase PDF ------------------
class PDFGeneral(FPDF):
    def __init__(self):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.set_auto_page_break(auto=True, margin=15)

        self._unicode = False
        fonts_folder = _resource_path('recursos', 'fonts')
        reg = os.path.join(fonts_folder, 'DejaVuSans.ttf')
        bold = os.path.join(fonts_folder, 'DejaVuSans-Bold.ttf')
        ital = os.path.join(fonts_folder, 'DejaVuSans-Oblique.ttf')

        if os.path.exists(reg) and os.path.exists(bold) and os.path.exists(ital):
            try:
                self.add_font("DejaVu", "", reg, uni=True)
                self.add_font("DejaVu", "B", bold, uni=True)
                self.add_font("DejaVu", "I", ital, uni=True)
                self.set_font("DejaVu", "", 7)
                self._unicode = True
            except Exception:
                self.set_font("Helvetica", "", 7)
        else:
            self.set_font("Helvetica", "", 7)

        self.titulo = ""
        self.columnas = []
        self.anchos = []
        self.feriados = set()
        self.grosor_linea_lunes = 0.6
        self.grosor_linea_normal = 0.2

    # -------------------------------------------  
    # HEADER  
    # -------------------------------------------  
    def header(self):
        fam = "DejaVu" if self._unicode else "Helvetica"
        self.set_font(fam, "B", 12)
        self.cell(0, 10, self.titulo, ln=1, align="C")
        self.ln(3)

    # -------------------------------------------  
    # FOOTER  
    # -------------------------------------------  
    def footer(self):
        fam = "DejaVu" if self._unicode else "Helvetica"
        self.set_y(-15)
        self.set_font(fam, "I", 8)
        self.cell(0, 10, f"Página {self.page_no()}", 0, 0, "L")

        self.set_y(-15)
        self.set_x(-70)
        self.set_font(fam, "I", 7)
        self.cell(60, 10, "Realizado por CM_Carola", 0, 0, "R")

    # -------------------------------------------  
    # PORTADA ELEGANTE  
    # -------------------------------------------  
    def portada_abreviaciones(self, mes=""):
        fam = "DejaVu" if self._unicode else "Helvetica"
        self.add_page()

        # Título general
        self.set_font(fam, "B", 18)
        self.cell(0, 15, "Informe de Fichadas", ln=1, align="C")

        # Subtítulo
        self.set_font(fam, "", 11)
        if mes:
            self.cell(0, 7, f"Período: {mes}", ln=1, align="C")
        self.ln(8)

        # Título de sección
        self.set_font(fam, "B", 13)
        self.cell(0, 10, "Leyenda de símbolos y abreviaturas", ln=1)
        self.ln(3)

        self.set_font(fam, "", 10)

        items = [
    "★ FER : Día feriado trabajado (todas las horas se liquidan al 100%).",
    "◆ SAB / ◆ DOM : Sábado / Domingo trabajado (fila gris clara; horas al 100%).",
    "✦ FR : Franco compensatorio generado (total diario redondeado ≥ 4 h al 100%).",
    "↘ EA : Entrada anticipada recortada (no se computa el tiempo previo al horario normal).",
    "✌ SA : Salida anticipada (no se cumplen las 7 h normales del día).",
    "△ INC : Fichada inconclusa (falta SALIDA o tramo inválido; el sistema asigna 0 h).",
    "COMIDA : Cantidad de comidas reconocidas según jornada continua.",
    "FRANCO : Cantidad de francos compensatorios generados (0 o 1 por día).",
    "Tarde : Llegada tarde (1 si la primera entrada fue ≥ hora límite configurada).",
    "Observaciones : Puede contener múltiples símbolos separados por '|'."
]


        for txt in items:
            self.multi_cell(0, 6, f"• {txt}")
            self.ln(1)

        self.ln(6)
        self.set_font(fam, "I", 9)
        self.multi_cell(
            0, 5,
            "Este informe es de uso interno. La interpretación depende del convenio de Luz y Fuerza."
        )

        self.ln(18)
        self.set_font(fam, "I", 10)
        self.set_text_color(80, 80, 80)
        self.cell(0, 6, "Desarrollado por CM_Carola", ln=1, align="R")
        self.set_text_color(0, 0, 0)

    # -------------------------------------------  
    # Encabezado por empleado  
    # -------------------------------------------  
    def encabezado_empleado(self, legajo, nombre="", departamento=""):
        fam = "DejaVu" if self._unicode else "Helvetica"
        self.set_font(fam, "B", 10)
        partes = [f"Legajo: {legajo}"]
        if nombre:
            partes.append(f"Nombre: {nombre}")
        if departamento:
            partes.append(f"Departamento: {departamento}")
        self.cell(0, 8, "   |   ".join(partes), ln=1)
        self.ln(1)

    # -------------------------------------------  
    # Títulos de tabla  
    # -------------------------------------------  
    def _titulos_columnas(self, columnas, anchos):
        fam = "DejaVu" if self._unicode else "Helvetica"
        self.set_font(fam, "B", 8)
        for col, ancho in zip(columnas, anchos):
            self.cell(ancho, 6, col, 1, 0, 'C')
        self.ln()
        self.set_font(fam, "", 7)

    # -------------------------------------------  
    # Decorador observaciones  
    # -------------------------------------------  
    def _decorar_observacion(self, texto):
        if not texto:
            return ""
        if not self._unicode:
            return texto

        # Si ya empieza con un símbolo, no lo duplicamos
        primer = texto.strip()[:1]
        if primer in ("↘", "✌", "✦", "★", "◆", "☹"):
            return texto

        t = texto.lower()
        if "tarde" in t:
            return f"☹ {texto}"
        if "ea" in t:
            return f"↘ {texto}"
        if "sa" in t:
            return f"✌ {texto}"
        if "fr" in t:
            return f"✦ {texto}"
        if "fer" in t:
            return f"★ {texto}"
        if "sab" in t or "dom" in t:
            return f"◆ {texto}"
        return texto
    # -------------------------------------------  
    # TABLA COMPLETA DE REGISTROS  
    # -------------------------------------------  
    def tabla_registros(self, registros, excluido_ot=False):

        columnas = ["Fecha","Entrada","Salida","Normales","50%","100%","Comida","Franco","Tarde","Observaciones"]
        anchos = [16,16,16,18,16,16,12,12,12,50]

        self.columnas = columnas
        self.anchos = anchos

        self._titulos_columnas(columnas, anchos)

        fam = "DejaVu" if self._unicode else "Helvetica"

        tot_norm = timedelta(0)
        tot50 = timedelta(0)
        tot100 = timedelta(0)
        tot_com = 0
        tot_fr = 0
        tot_tarde = 0

        for r in registros:
            # Re-imprimir encabezados si no hay espacio para la siguiente fila
            if self.get_y() + 6 > self.h - self.b_margin:
                self.add_page()
                self._titulos_columnas(columnas, anchos)
            fecha = r.get("Fecha","")
            d = _parse_fecha(fecha)
            es_feriado = False
            es_finde = False

            if d:
                if d.strftime("%Y-%m-%d") in self.feriados or fecha in self.feriados:
                    es_feriado = True
                if d.weekday() in (5,6):
                    es_finde = True

                if d.weekday() == 0:  # lunes línea gruesa
                    y = self.get_y()
                    x = self.get_x()
                    self.set_line_width(self.grosor_linea_lunes)
                    self.line(x, y, x + sum(anchos), y)
                    self.set_line_width(self.grosor_linea_normal)

            # FERIADO = texto rojo  
            if es_feriado:
                self.set_text_color(200,0,0)

            # FINDE = fondo gris suave
            if es_finde and not es_feriado:
                self.set_fill_color(235,235,235)
                fill_row = True
            else:
                fill_row = False

            # Datos del registro
            norm  = _td_from_any(r.get("Normales","00:00:00"))
            e50   = timedelta(0) if excluido_ot else _td_from_any(r.get("50%","00:00:00"))
            e100  = timedelta(0) if excluido_ot else _td_from_any(r.get("100%","00:00:00"))
            raw_obs = r.get("Observaciones","")
            obs = self._decorar_observacion(raw_obs)

            # Celdas
            self.cell(anchos[0],6,fecha,1,0,'',fill_row)
            self.cell(anchos[1],6,str(r.get("Entrada","")),1,0,'',fill_row)
            self.cell(anchos[2],6,str(r.get("Salida","")),1,0,'',fill_row)
            self.cell(anchos[3],6,formato_horas(norm),1,0,'C',fill_row)
            self.cell(anchos[4],6,formato_horas(e50),1,0,'C',fill_row)
            self.cell(anchos[5],6,formato_horas(e100),1,0,'C',fill_row)
            self.cell(anchos[6],6,str(int(r.get("COMIDA",0))),1,0,'C',fill_row)
            self.cell(anchos[7],6,str(int(r.get("FRANCO",0))),1,0,'C',fill_row)
            self.cell(anchos[8],6,str(int(r.get("Tarde",0))),1,0,'C',fill_row)

            # Colores observaciones
            if self._unicode and raw_obs:
                u = raw_obs.upper()
                if "FER" in u:
                    self.set_text_color(200,0,0)
                elif "SAB" in u or "DOM" in u:
                    self.set_text_color(0,60,130)
                elif "FR" in u:
                    self.set_text_color(180,120,0)
                elif "EA" in u:
                    self.set_text_color(90,90,90)
                elif "SA" in u:
                    self.set_text_color(200,120,0)
                elif "TARDE" in u:
                    self.set_text_color(160,0,160)

            self.cell(anchos[9],6,obs,1,0,'',fill_row)

            self.set_text_color(0,0,0)
            if es_finde and not es_feriado:
                self.set_fill_color(255,255,255)

            self.ln()

            # Totales
            tot_norm += norm
            tot50 += e50
            tot100 += e100
            tot_com += int(r.get("COMIDA",0))
            tot_fr += int(r.get("FRANCO",0))
            tot_tarde += int(r.get("Tarde",0))

        # Totales
        self.set_font(fam,"B",8)
        self.cell(0,6,"Totales del mes:",ln=1)
        self.cell(0,6,f"Horas Normales: {formato_horas(tot_norm)}",ln=1)
        self.cell(0,6,f"Horas 50%: {formato_horas(_round_to_hour(tot50))}",ln=1)
        self.cell(0,6,f"Horas 100%: {formato_horas(_round_to_hour(tot100))}",ln=1)
        self.cell(0,6,f"Comidas: {tot_com}",ln=1)
        self.cell(0,6,f"Francos: {tot_fr}",ln=1)
        self.cell(0,6,f"Llegadas tarde: {tot_tarde}",ln=1)
        self.ln(4)

# --------------------------------------------  
# GENERAR PDF GENERAL  
# --------------------------------------------
def _legajo_sort_key(x):
    leg = str(x.get("legajo", ""))
    try:
        return int(leg)
    except ValueError:
        return 0

def generar_pdf_general(data, mes, salida=None, feriados=None, grosor_lunes=0.6):
    pdf = PDFGeneral()
    pdf.titulo = f"Informe de Fichadas - {mes}"
    pdf.feriados = set(feriados or [])
    pdf.grosor_linea_lunes = grosor_lunes

    pdf.portada_abreviaciones(mes)
    pdf.add_page()

    for i, empleado in enumerate(sorted(data, key=_legajo_sort_key)):
        if i > 0:
            espacio = pdf.h - pdf.get_y() - pdf.b_margin
            if espacio < 40:
                pdf.add_page()
            else:
                pdf.ln(3)
                pdf.set_draw_color(160, 160, 160)
                pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
                pdf.set_draw_color(0, 0, 0)
                pdf.ln(3)
        pdf.encabezado_empleado(
            empleado.get("legajo",""),
            empleado.get("nombre",""),
            empleado.get("departamento","")
        )
        pdf.tabla_registros(empleado.get("registros",[]),
                            excluido_ot=empleado.get("excluido_ot", False))

    if salida:
        pdf.output(salida)
        return os.path.abspath(salida)
    raw = pdf.output(dest="S")
    return raw.encode("latin-1") if isinstance(raw, str) else bytes(raw)

# --------------------------------------------  
# GENERAR PDF RESUMEN  
# --------------------------------------------
def generar_pdf_resumen(data, mes, salida=None, feriados=None, grosor_lunes=0.6):
    pdf = PDFGeneral()
    pdf.titulo = f"Resumen de Totales - {mes}"
    pdf.feriados = set(feriados or [])
    pdf.grosor_linea_lunes = grosor_lunes

    columnas = ["Legajo","Nombre","Normales","50%","100%","COMIDA","FRANCO","Tarde"]
    anchos   = [20,40,20,20,20,15,15,15]
    pdf.columnas = columnas
    pdf.anchos = anchos

    pdf.add_page()
    fam = "DejaVu" if pdf._unicode else "Helvetica"
    pdf.set_font(fam,"B",8)

    for col, ancho in zip(columnas, anchos):
        pdf.cell(ancho,6,col,1,0,'C')
    pdf.ln()

    tot_norm = timedelta(0)
    tot_50   = timedelta(0)
    tot_100  = timedelta(0)
    tot_com  = 0
    tot_fr   = 0
    tot_tar  = 0

    for emp in sorted(data, key=_legajo_sort_key):
        leg = emp.get("legajo","")
        nom = emp.get("nombre","")
        regs = emp.get("registros",[])
        excl = emp.get("excluido_ot", False)

        e_norm=timedelta(0)
        e_50  =timedelta(0)
        e_100 =timedelta(0)
        e_com =0
        e_fr  =0
        e_tar =0

        for r in regs:
            e_norm += _td_from_any(r.get("Normales","00:00:00"))
            if not excl:
                e_50  += _td_from_any(r.get("50%","00:00:00"))
                e_100 += _td_from_any(r.get("100%","00:00:00"))
            e_com  += int(r.get("COMIDA",0))
            e_fr   += int(r.get("FRANCO",0))
            e_tar  += int(r.get("Tarde",0))

        tot_norm += e_norm
        tot_50   += e_50
        tot_100  += e_100
        tot_com  += e_com
        tot_fr   += e_fr
        tot_tar  += e_tar

        # Salto de página con repetición de encabezados si no entra la fila
        if pdf.get_y() + 5 > pdf.h - pdf.b_margin:
            pdf.add_page()
            pdf.set_font(fam,"B",8)
            for col, ancho in zip(columnas, anchos):
                pdf.cell(ancho,6,col,1,0,'C')
            pdf.ln()

        pdf.set_font(fam,"",7)
        fila = [
            str(leg),
            nom,
            formato_horas(e_norm),
            formato_horas(_round_to_hour(e_50)),
            formato_horas(_round_to_hour(e_100)),
            str(e_com),
            str(e_fr),
            str(e_tar),
        ]

        for dato, ancho in zip(fila, anchos):
            pdf.cell(ancho,5,dato,1)
        pdf.ln()

    pdf.set_font(fam,"B",8)
    pdf.cell(anchos[0]+anchos[1],6,"TOTALES",1,0,"R")
    pdf.cell(anchos[2],6,formato_horas(tot_norm),1)
    pdf.cell(anchos[3],6,formato_horas(_round_to_hour(tot_50)),1)
    pdf.cell(anchos[4],6,formato_horas(_round_to_hour(tot_100)),1)
    pdf.cell(anchos[5],6,str(tot_com),1)
    pdf.cell(anchos[6],6,str(tot_fr),1)
    pdf.cell(anchos[7],6,str(tot_tar),1)
    pdf.ln()

    if salida:
        pdf.output(salida)
        return os.path.abspath(salida)
    raw = pdf.output(dest="S")
    return raw.encode("latin-1") if isinstance(raw, str) else bytes(raw)

