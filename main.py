# -*- coding: utf-8 -*-
VERSION = "1.2.0"

# ─── Fuente y paleta global ──────────────────────────────────────────────────
_F        = "Segoe UI"
FONT_SM   = (_F,  9)
FONT_BASE = (_F, 10)
FONT_BOLD = (_F, 10, "bold")
FONT_TITLE= (_F, 18, "bold")
FONT_H2   = (_F, 13, "bold")
FONT_MONO = ("Consolas", 10)

BG_WIN   = "#f2faff"
BG_FRAME = "#e7f5ff"
C_TITLE  = "#1a435b"
C_PRI    = "#71c7ec"   # azul — acción principal
C_OK     = "#afe9b7"   # verde — guardar / OK
C_DEL    = "#f4978e"   # rojo  — eliminar / salir
C_WARN   = "#ffd6a5"   # naranja — limpiar / advertencia
C_NEU    = "#d9eaf7"   # gris-azul — cerrar / neutro

import os
import sys
import ctypes
import datetime
import webbrowser
from datetime import timedelta
from pathlib import Path

import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox

from PIL import Image, ImageTk
import pandas as pd
import inspect
import calendar
import json
from horarios_paro import cargar_horarios_paro, guardar_horarios_paro

from procesador import procesar_fichadas, aplanar_registros_por_tramo
from pdf_generator import generar_pdf_general, generar_pdf_resumen
from feriados_gui import abrir_gestor_feriados, cargar_feriados

# =============================================================================
# IMPORTS OPCIONALES (no deben romper la app)
# =============================================================================
RESUMEN_UI_DISPONIBLE = False
RESUMEN_UI_ERROR = ""
try:
    from resumen_ui import mostrar_resumen
    RESUMEN_UI_DISPONIBLE = True
except Exception as e:
    RESUMEN_UI_DISPONIBLE = False
    RESUMEN_UI_ERROR = str(e)

RESUMEN_ESTADISTICO_DISPONIBLE = False
try:
    from resumen_estadistico import generar_resumen
    RESUMEN_ESTADISTICO_DISPONIBLE = True
except Exception:
    RESUMEN_ESTADISTICO_DISPONIBLE = False

GRAFICOS_DISPONIBLE = False
GRAFICOS_ERROR = ""
try:
    from graficos_ui import mostrar_panel_graficos
    GRAFICOS_DISPONIBLE = True
except Exception as e:
    GRAFICOS_DISPONIBLE = False
    GRAFICOS_ERROR = str(e)

# =============================================================================
# CONFIGURACIÓN: LEGAJOS EXCLUIDOS DE CONTROL DE TARDANZA
# =============================================================================
EXCLUIR_TARDANZA = {
    # "1234",  # Ing. Mancioni
    # "5678",  # Ing. Gatti
}

# =============================================================================
# CONFIG DE INICIOS (detección multi-bloque por día/depto)
# =============================================================================
INICIO_VARIABLE = {
    "allowed": ["05:00", "05:30", "06:00", "06:30"],
    "default": "06:00",
    "por_departamento": {
        "Redes": {"default": "06:00"}   # opcional, baseline
    },
    "bloques_multiples": {
        "activar": True,
        "ventana": ("04:45", "07:30"),
        "tolerancia_min": 12,   # ±12'
        "quorum_abs": 3,
        "quorum_pct": 0.60,
        "max_bloques_por_dia": 2
    },
    # Solo metadata visual; el recorte real lo hace procesador.py
    "gracia_entrada_min": 25,
    "anotar_entrada_fuera_de_gracia": True
}

# =============================================================================
# ESTADO GLOBAL (para menú "Ver → Gráficos" y "Ver → Resumen")
# =============================================================================
ULTIMOS_RESULTADOS_APLANADOS = None   # lista aplanada lista para resumen/gráficos
ULTIMO_PERIODO_TEXTO = ""             # ej: "Enero 2025 - Diciembre 2025"
ULTIMO_ARCHIVO = ""                   # nombre archivo procesado

# =============================================================================
# VERSIÓN
# =============================================================================
def get_version():
    try:
        with open(os.path.join("recursos", "version.txt"), "r", encoding="utf-8") as f:
            v = f.read().strip()
            if v:
                return v
    except Exception:
        pass
    return VERSION

if __name__ == "__main__":
    print(f"CM_HorasExtras v{get_version()}")

# =============================================================================
# DIRECTORIOS
# =============================================================================
if getattr(sys, 'frozen', False):
    BASE_DIR      = os.path.dirname(sys.executable)
    _BUNDLE_DIR   = sys._MEIPASS          # archivos bundleados dentro del exe
else:
    BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
    _BUNDLE_DIR   = BASE_DIR

def _resource(relpath):
    """Ruta a un recurso bundleado (logo, fuentes). Funciona frozen y en dev."""
    return os.path.join(_BUNDLE_DIR, relpath)

CARPETA_ARCHIVOS = os.path.join(BASE_DIR, "archivos")
CARPETA_REPORTES = os.path.join(BASE_DIR, "reportes")

# Recursos bundleados (icono de ventana/taskbar y logo de pantalla)
CARPETA_RECURSOS = _resource("recursos")
ICON_ICO = _resource(os.path.join("recursos", "logo.ico"))
ICON_PNG = _resource(os.path.join("recursos", "logo.png"))

# Logo de pantalla (usa el bundleado en recursos/)
LOGO_PATH = _resource(os.path.join("recursos", "logo.png"))

os.makedirs(CARPETA_ARCHIVOS, exist_ok=True)
os.makedirs(CARPETA_REPORTES, exist_ok=True)

# =============================================================================
# APP ID (Windows taskbar icon)
# =============================================================================
def set_app_id():
    if sys.platform == "win32":
        try:
            # OJO: este ID debe quedar estable (no por versión) para evitar “iconos que se van”
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CMHorasExtras.App")
        except Exception:
            pass

set_app_id()

# =============================================================================
# HELPERS
# =============================================================================
def _fmt_td(x):
    if isinstance(x, timedelta):
        total = int(x.total_seconds())
        hh = total // 3600
        mm = (total % 3600) // 60
        ss = total % 60
        return f"{hh:02}:{mm:02}:{ss:02}"
    return str(x or "")

def seleccionar_archivo_con_fecha(archivos_disp, carpeta, parent=None):
    win = tk.Toplevel(parent) if parent else tk.Toplevel()
    win.title("Seleccionar archivo a procesar")
    win.geometry("660x360")
    win.configure(bg=BG_WIN)

    tk.Label(
        win, text="Seleccioná un archivo de la lista:",
        font=FONT_H2, bg=BG_WIN, fg=C_TITLE
    ).pack(pady=(10, 4))

    frm_lista = tk.Frame(win, bg=BG_WIN)
    frm_lista.pack(expand=True, fill="both", padx=16, pady=2)

    sb_lista = ttk.Scrollbar(frm_lista, orient="vertical")
    lista = tk.Listbox(
        frm_lista, font=FONT_BASE, height=12,
        yscrollcommand=sb_lista.set, selectbackground=C_PRI,
        relief=tk.FLAT, bd=1, highlightthickness=1
    )
    sb_lista.config(command=lista.yview)

    archivos_mostrados = []

    for f in archivos_disp:
        ruta_f = os.path.join(carpeta, f)
        fecha = os.path.getmtime(ruta_f)
        fecha_fmt = datetime.datetime.fromtimestamp(fecha).strftime('%d/%m/%Y %H:%M')
        label_f = f"{f}   (últ. modif: {fecha_fmt})"
        archivos_mostrados.append((f, label_f, fecha))
        lista.insert(tk.END, label_f)

    lista.pack(side="left", expand=True, fill="both")
    sb_lista.pack(side="right", fill="y")

    seleccionado = {"nombre": None}

    def confirmar():
        try:
            idx = lista.curselection()[0]
            seleccionado["nombre"] = archivos_mostrados[idx][0]
            win.destroy()
        except IndexError:
            messagebox.showwarning("Atención", "Seleccioná un archivo.", parent=win)

    tk.Button(
        win,
        text="Procesar archivo seleccionado",
        command=confirmar,
        font=FONT_BOLD,
        bg=C_PRI,
        width=30
    ).pack(pady=8)

    if parent:
        win.transient(parent)
    win.grab_set()
    win.focus_set()
    win.wait_window()
    return seleccionado["nombre"]

def mostrar_detallado_en_pantalla(data, parent=None):
    win = tk.Toplevel(parent) if parent else tk.Toplevel()
    win.title("Detalle de Fichadas por Empleado")
    win.geometry("1260x580")
    win.configure(bg=BG_WIN)

    frm_tv = tk.Frame(win)
    frm_tv.pack(expand=True, fill="both", padx=6, pady=6)

    columnas = ["Legajo", "Nombre", "Fecha", "Entrada", "Salida", "Normales", "50%", "100%", "Tarde", "FRANCO", "COMIDA", "Observaciones"]
    tree = ttk.Treeview(frm_tv, columns=columnas, show="headings", height=20)

    for col in columnas:
        tree.heading(col, text=col)
        ancho = 100 if col not in ("Nombre", "Observaciones") else (180 if col == "Nombre" else 240)
        tree.column(col, width=ancho, anchor='center')

    sb_tv_y = ttk.Scrollbar(frm_tv, orient="vertical",   command=tree.yview)
    sb_tv_x = ttk.Scrollbar(frm_tv, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=sb_tv_y.set, xscrollcommand=sb_tv_x.set)

    sb_tv_y.pack(side="right",  fill="y")
    sb_tv_x.pack(side="bottom", fill="x")
    tree.pack(expand=True, fill="both")

    # data puede venir:
    # - lista por empleado con "registros"
    # - o lista plana (ya aplanada)
    if isinstance(data, list) and data and isinstance(data[0], dict) and "registros" in data[0]:
        for emp in data:
            legajo = emp.get("legajo", "")
            nombre = emp.get("nombre", "")
            registros = emp.get("registros", [])
            for r in registros:
                tree.insert("", "end", values=[
                    legajo,
                    nombre,
                    r.get("Fecha", ""),
                    r.get("Entrada", ""),
                    r.get("Salida", ""),
                    _fmt_td(r.get("Normales", "")),
                    _fmt_td(r.get("50%", "")),
                    _fmt_td(r.get("100%", "")),
                    r.get("Tarde", ""),
                    r.get("FRANCO", ""),
                    r.get("COMIDA", ""),
                    r.get("Observaciones", "")
                ])
    else:
        for r in (data or []):
            if not isinstance(r, dict):
                continue
            tree.insert("", "end", values=[
                r.get("Legajo", r.get("legajo", "")),
                r.get("Nombre", r.get("nombre", "")),
                r.get("Fecha", ""),
                r.get("Entrada", ""),
                r.get("Salida", ""),
                _fmt_td(r.get("Normales", "")),
                _fmt_td(r.get("50%", "")),
                _fmt_td(r.get("100%", "")),
                r.get("Tarde", ""),
                r.get("FRANCO", ""),
                r.get("COMIDA", ""),
                r.get("Observaciones", "")
            ])

    if parent:
        win.transient(parent)
    win.grab_set()
    win.focus_set()
    win.wait_window()

# =============================================================================
# MENÚ: acciones
# =============================================================================
def _accion_salir():
    ventana.destroy()

def _accion_gestionar_feriados():
    abrir_gestor_feriados()

def _accion_ver_graficos():
    global ULTIMOS_RESULTADOS_APLANADOS, ULTIMO_PERIODO_TEXTO

    if not GRAFICOS_DISPONIBLE:
        messagebox.showwarning(
            "Gráficos no disponibles",
            "No se pudo cargar el módulo de gráficos.\n\n"
            f"Motivo:\n{GRAFICOS_ERROR}",
            parent=ventana
        )
        return

    if ULTIMOS_RESULTADOS_APLANADOS is None:
        messagebox.showwarning(
            "Atención",
            "Primero debés procesar un archivo (Cargar archivo de fichadas).",
            parent=ventana
        )
        return

    if not RESUMEN_ESTADISTICO_DISPONIBLE:
        messagebox.showwarning(
            "Atención",
            "No está disponible resumen_estadistico.py, no puedo armar los datos para gráficos.",
            parent=ventana
        )
        return

    try:
        resumen = generar_resumen(ULTIMOS_RESULTADOS_APLANADOS)
        mostrar_panel_graficos(
            resumen,
            carpeta_reportes=CARPETA_REPORTES,
            parent=ventana
        )
    except Exception as e:
        messagebox.showerror("Error", f"No se pudieron mostrar los gráficos:\n{e}", parent=ventana)


CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def abrir_gestor_horarios_paro():
    win = tk.Toplevel()
    win.title("Horarios Base Paro")
    win.geometry("420x280")
    win.configure(bg=BG_WIN)
    win.resizable(False, False)

    horarios = cargar_horarios_paro()

    tk.Label(
        win, text="Horarios Base de Paro",
        font=FONT_H2, bg=BG_WIN, fg=C_TITLE
    ).pack(pady=(10, 6))

    frm = tk.Frame(win, bg=BG_FRAME, relief=tk.RIDGE, bd=2)
    frm.pack(fill="x", padx=16, pady=2)
    frm.columnconfigure(1, weight=1)

    def _lbl(text, row):
        tk.Label(frm, text=text, bg=BG_FRAME, font=FONT_BASE, anchor="e").grid(
            row=row, column=0, padx=(12, 6), pady=6, sticky="e"
        )

    _lbl("Año", 0)
    entry_anio = tk.Entry(frm, width=10, font=FONT_BASE)
    entry_anio.insert(0, "2026")
    entry_anio.grid(row=0, column=1, padx=(0, 12), pady=6, sticky="w")

    _lbl("Mes (1-12)", 1)
    entry_mes = tk.Entry(frm, width=10, font=FONT_BASE)
    entry_mes.insert(0, "2")
    entry_mes.grid(row=1, column=1, padx=(0, 12), pady=6, sticky="w")

    _lbl("Departamento", 2)
    departamentos = ["Redes", "Administracion", "Guardias", "Telefonista", "Internet"]
    combo_depto = ttk.Combobox(frm, values=departamentos, state="readonly", width=20)
    combo_depto.set("Redes")
    combo_depto.grid(row=2, column=1, padx=(0, 12), pady=6, sticky="w")

    _lbl("Hora inicio (HH:MM)", 3)
    entry_hora = tk.Entry(frm, width=10, font=FONT_BASE)
    entry_hora.insert(0, "06:00")
    entry_hora.grid(row=3, column=1, padx=(0, 12), pady=6, sticky="w")

    def cargar_existente():
        anio = entry_anio.get().strip()
        mes_txt = entry_mes.get().strip()
        depto = combo_depto.get().strip().lower()
        if not anio or not mes_txt.isdigit():
            return
        mes = int(mes_txt)
        if mes < 1 or mes > 12:
            return
        clave = f"{anio}-{mes:02d}"
        hora_existente = horarios.get(depto, {}).get(clave)
        entry_hora.delete(0, tk.END)
        if hora_existente:
            entry_hora.insert(0, hora_existente)
        else:
            entry_hora.insert(0, "05:00" if depto == "redes" else "06:00")

    def guardar():
        anio = entry_anio.get().strip()
        mes_txt = entry_mes.get().strip()
        depto = combo_depto.get().strip().lower()
        hora = entry_hora.get().strip()
        if not anio.isdigit() or len(anio) != 4:
            messagebox.showerror("Error", "El año debe tener 4 dígitos.", parent=win)
            return
        if not mes_txt.isdigit():
            messagebox.showerror("Error", "El mes debe ser numérico.", parent=win)
            return
        mes = int(mes_txt)
        if mes < 1 or mes > 12:
            messagebox.showerror("Error", "El mes debe estar entre 1 y 12.", parent=win)
            return
        if len(hora) != 5 or hora[2] != ":":
            messagebox.showerror("Error", "La hora debe tener formato HH:MM.", parent=win)
            return
        try:
            hh, mm = map(int, hora.split(":"))
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Hora inválida. Use formato HH:MM.", parent=win)
            return
        clave = f"{anio}-{mes:02d}"
        if depto not in horarios:
            horarios[depto] = {}
        horarios[depto][clave] = hora
        guardar_horarios_paro(horarios)
        messagebox.showinfo("OK", "Horario guardado correctamente.", parent=win)

    def eliminar():
        anio = entry_anio.get().strip()
        mes_txt = entry_mes.get().strip()
        depto = combo_depto.get().strip().lower()
        if not anio.isdigit() or len(anio) != 4:
            messagebox.showerror("Error", "Año inválido.", parent=win)
            return
        if not mes_txt.isdigit():
            messagebox.showerror("Error", "Mes inválido.", parent=win)
            return
        mes = int(mes_txt)
        if mes < 1 or mes > 12:
            messagebox.showerror("Error", "El mes debe estar entre 1 y 12.", parent=win)
            return
        clave = f"{anio}-{mes:02d}"
        if depto in horarios and clave in horarios[depto]:
            del horarios[depto][clave]
            if not horarios[depto]:
                del horarios[depto]
            guardar_horarios_paro(horarios)
            entry_hora.delete(0, tk.END)
            messagebox.showinfo("OK", "Horario eliminado correctamente.", parent=win)
        else:
            messagebox.showwarning("Aviso", "No existe un horario guardado para ese mes/departamento.", parent=win)

    entry_anio.bind("<FocusOut>",          lambda e: cargar_existente())
    entry_mes.bind("<FocusOut>",           lambda e: cargar_existente())
    combo_depto.bind("<<ComboboxSelected>>", lambda e: cargar_existente())

    btn_frm = tk.Frame(win, bg=BG_WIN)
    btn_frm.pack(pady=10)
    tk.Button(btn_frm, text="Guardar",  command=guardar,     bg=C_OK,  font=FONT_BOLD, width=11).pack(side="left", padx=6)
    tk.Button(btn_frm, text="Eliminar", command=eliminar,    bg=C_DEL, font=FONT_BOLD, width=11).pack(side="left", padx=6)
    tk.Button(btn_frm, text="Cerrar",   command=win.destroy, bg=C_NEU, font=FONT_BOLD, width=9 ).pack(side="left", padx=6)

    cargar_existente()

def abrir_gestor_dias_paro():
    win = tk.Toplevel(ventana)
    win.title("Gestionar Días de Paro")
    win.geometry("520x500")

    hoy = datetime.datetime.now()
    mes_var = tk.IntVar(value=hoy.month)
    anio_var = tk.IntVar(value=hoy.year)

    frame_fecha = tk.Frame(win)
    frame_fecha.pack(pady=10)

    tk.Label(frame_fecha, text="Mes").grid(row=0, column=0, padx=5)
    tk.Spinbox(
        frame_fecha,
        from_=1,
        to=12,
        textvariable=mes_var,
        width=5,
        command=lambda: generar_calendario()
    ).grid(row=0, column=1)

    tk.Label(frame_fecha, text="Año").grid(row=0, column=2, padx=5)
    tk.Spinbox(
        frame_fecha,
        from_=2024,
        to=2035,
        textvariable=anio_var,
        width=6,
        command=lambda: generar_calendario()
    ).grid(row=0, column=3)

    lbl_info = tk.Label(
        win,
        text="Seleccioná los días de paro. Se conservarán los de otros meses.",
        font=FONT_BASE,
        fg=C_TITLE,
        bg=BG_WIN
    )
    lbl_info.pack(pady=(0, 6))

    dias_frame = tk.Frame(win)
    dias_frame.pack(pady=10)

    botones = {}

    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {}

    # Mantener TODOS los días de paro ya guardados, no solo el mes visible.
    dias_paro_guardados = set(config.get("dias_paro", []))

    def fecha_str_actual(dia):
        return datetime.date(anio_var.get(), mes_var.get(), dia).strftime("%Y-%m-%d")

    def toggle(fecha_iso):
        if fecha_iso in dias_paro_guardados:
            dias_paro_guardados.remove(fecha_iso)
            botones[fecha_iso].configure(bg="SystemButtonFace")
        else:
            dias_paro_guardados.add(fecha_iso)
            botones[fecha_iso].configure(bg="#ff6b6b")
        actualizar_resumen()

    def actualizar_resumen():
        ym = f"{anio_var.get()}-{mes_var.get():02d}"
        seleccionados_mes = sorted(f for f in dias_paro_guardados if f.startswith(ym + "-"))
        if seleccionados_mes:
            dias_txt = ", ".join(f[-2:] for f in seleccionados_mes)
            lbl_resumen.config(text=f"Días marcados del mes: {dias_txt}")
        else:
            lbl_resumen.config(text="Días marcados del mes: ninguno")

    def generar_calendario():
        for widget in dias_frame.winfo_children():
            widget.destroy()
        botones.clear()

        dias_semana = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sa", "Do"]
        for c, nombre in enumerate(dias_semana):
            tk.Label(dias_frame, text=nombre, font=("Segoe UI", 9, "bold")).grid(row=0, column=c, padx=2, pady=2)

        cal = calendar.monthcalendar(anio_var.get(), mes_var.get())

        for r, semana in enumerate(cal, start=1):
            for c, dia in enumerate(semana):
                if dia == 0:
                    continue

                fecha_iso = fecha_str_actual(dia)

                btn = tk.Button(
                    dias_frame,
                    text=str(dia),
                    width=4,
                    command=lambda f=fecha_iso: toggle(f)
                )

                if fecha_iso in dias_paro_guardados:
                    btn.configure(bg="#ff6b6b")

                btn.grid(row=r, column=c, padx=2, pady=2)
                botones[fecha_iso] = btn

        actualizar_resumen()

    def limpiar_mes_actual():
        ym = f"{anio_var.get()}-{mes_var.get():02d}"
        a_borrar = {f for f in dias_paro_guardados if f.startswith(ym + "-")}
        if not a_borrar:
            messagebox.showinfo("Aviso", "No hay días de paro marcados en este mes.", parent=win)
            return

        for f in a_borrar:
            dias_paro_guardados.discard(f)

        generar_calendario()
        messagebox.showinfo("OK", "Se limpiaron los días de paro del mes actual.", parent=win)

    def guardar():
        config["dias_paro"] = sorted(dias_paro_guardados)

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        messagebox.showinfo("OK", "Días de paro guardados correctamente.", parent=win)
        win.destroy()

    lbl_resumen = tk.Label(win, text="", font=FONT_BOLD, fg="#8a1c1c", bg=BG_WIN)
    lbl_resumen.pack(pady=(0, 8))

    frame_botones = tk.Frame(win)
    frame_botones.pack(pady=6)

    tk.Button(frame_botones, text="Actualizar calendario", command=generar_calendario, bg=C_PRI,  font=FONT_BOLD).grid(row=0, column=0, padx=5)
    tk.Button(frame_botones, text="Limpiar mes actual",    command=limpiar_mes_actual, bg=C_WARN, font=FONT_BOLD).grid(row=0, column=1, padx=5)
    tk.Button(frame_botones, text="Guardar",               command=guardar,            bg=C_OK,   font=FONT_BOLD).grid(row=0, column=2, padx=5)

    generar_calendario()

def abrir_gestor_asignaciones_especiales():
    import tkinter as tk
    from tkinter import ttk, messagebox
    import json
    import os
    import re
    from datetime import datetime

    win = tk.Toplevel(ventana)
    win.title("Asignaciones Especiales")
    win.geometry("840x510")
    win.configure(bg="#f2faff")
    win.transient(ventana)
    win.grab_set()

    config_path = os.path.join(BASE_DIR, "config.json")

    edit_index = {"value": None}

    # -----------------------------
    # Helpers
    # -----------------------------
    def cargar_config():
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def guardar_config(data):
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def validar_fecha(fecha_txt):
        try:
            return datetime.strptime(fecha_txt, "%Y-%m-%d").date()
        except Exception:
            return None

    def validar_hora(hora_txt):
        if not re.match(r"^\d{2}:\d{2}$", hora_txt or ""):
            return False
        try:
            hh, mm = map(int, hora_txt.split(":"))
            return 0 <= hh <= 23 and 0 <= mm <= 59
        except Exception:
            return False

    def obtener_asignaciones():
        data = cargar_config()
        asignaciones = data.get("asignaciones_especiales", [])
        if not isinstance(asignaciones, list):
            asignaciones = []
        return data, asignaciones

    def recargar_grilla():
        for item in tree.get_children():
            tree.delete(item)

        _, asignaciones = obtener_asignaciones()

        asignaciones_ordenadas = sorted(
            asignaciones,
            key=lambda a: (
                str(a.get("legajo", "")).strip(),
                str(a.get("desde", "")).strip(),
                str(a.get("hasta", "")).strip(),
                str(a.get("tipo", "")).strip()
            )
        )

        for idx, a in enumerate(asignaciones_ordenadas):
            tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    a.get("legajo", ""),
                    a.get("tipo", ""),
                    a.get("desde", ""),
                    a.get("hasta", ""),
                    a.get("inicio", "")
                )
            )

        # guardamos también la lista ordenada visible
        tree.asignaciones_visibles = asignaciones_ordenadas

    def limpiar_formulario():
        entry_legajo.delete(0, tk.END)
        combo_tipo.set("CORTADOR")
        entry_desde.delete(0, tk.END)
        entry_hasta.delete(0, tk.END)
        entry_hora.delete(0, tk.END)
        entry_hora.insert(0, "06:00")
        edit_index["value"] = None
        lbl_modo.config(text="Modo: Alta")

    def cargar_seleccion():
        seleccion = tree.selection()
        if not seleccion:
            messagebox.showwarning("Atención", "Seleccioná una fila de la grilla.", parent=win)
            return

        iid = seleccion[0]
        idx = int(iid)

        visibles = getattr(tree, "asignaciones_visibles", [])
        if idx < 0 or idx >= len(visibles):
            messagebox.showerror("Error", "No se pudo recuperar la fila seleccionada.", parent=win)
            return

        a = visibles[idx]

        entry_legajo.delete(0, tk.END)
        entry_legajo.insert(0, str(a.get("legajo", "")))

        combo_tipo.set(str(a.get("tipo", "CORTADOR")))

        entry_desde.delete(0, tk.END)
        entry_desde.insert(0, str(a.get("desde", "")))

        entry_hasta.delete(0, tk.END)
        entry_hasta.insert(0, str(a.get("hasta", "")))

        entry_hora.delete(0, tk.END)
        entry_hora.insert(0, str(a.get("inicio", "06:00")))

        edit_index["value"] = a
        lbl_modo.config(text="Modo: Modificación")

    def validar_campos():
        legajo = entry_legajo.get().strip()
        tipo = combo_tipo.get().strip().upper()
        desde = entry_desde.get().strip()
        hasta = entry_hasta.get().strip()
        hora = entry_hora.get().strip()

        if not legajo:
            messagebox.showerror("Error", "Ingresá un legajo.", parent=win)
            return None

        if not tipo:
            messagebox.showerror("Error", "Seleccioná un tipo.", parent=win)
            return None

        f_desde = validar_fecha(desde)
        if not f_desde:
            messagebox.showerror("Error", "La fecha Desde es inválida. Usá YYYY-MM-DD.", parent=win)
            return None

        f_hasta = validar_fecha(hasta)
        if not f_hasta:
            messagebox.showerror("Error", "La fecha Hasta es inválida. Usá YYYY-MM-DD.", parent=win)
            return None

        if f_desde > f_hasta:
            messagebox.showerror("Error", "La fecha Desde no puede ser mayor que Hasta.", parent=win)
            return None

        if not validar_hora(hora):
            messagebox.showerror("Error", "La hora es inválida. Usá HH:MM.", parent=win)
            return None

        return {
            "legajo": legajo,
            "tipo": tipo,
            "desde": desde,
            "hasta": hasta,
            "inicio": hora
        }

    def guardar():
        nuevo = validar_campos()
        if not nuevo:
            return

        data, asignaciones = obtener_asignaciones()

        # evitar duplicado exacto en alta
        if edit_index["value"] is None:
            existe = any(
                str(a.get("legajo", "")).strip() == nuevo["legajo"]
                and str(a.get("tipo", "")).strip().upper() == nuevo["tipo"]
                and str(a.get("desde", "")).strip() == nuevo["desde"]
                and str(a.get("hasta", "")).strip() == nuevo["hasta"]
                and str(a.get("inicio", "")).strip() == nuevo["inicio"]
                for a in asignaciones
            )
            if existe:
                messagebox.showwarning("Aviso", "Esa asignación ya existe.", parent=win)
                return

            asignaciones.append(nuevo)
            data["asignaciones_especiales"] = asignaciones
            guardar_config(data)
            recargar_grilla()
            limpiar_formulario()
            messagebox.showinfo("OK", "Asignación guardada correctamente.", parent=win)
            return

        # modificación
        original = edit_index["value"]
        modificado = False

        for i, a in enumerate(asignaciones):
            if (
                str(a.get("legajo", "")).strip() == str(original.get("legajo", "")).strip()
                and str(a.get("tipo", "")).strip().upper() == str(original.get("tipo", "")).strip().upper()
                and str(a.get("desde", "")).strip() == str(original.get("desde", "")).strip()
                and str(a.get("hasta", "")).strip() == str(original.get("hasta", "")).strip()
                and str(a.get("inicio", "")).strip() == str(original.get("inicio", "")).strip()
            ):
                asignaciones[i] = nuevo
                modificado = True
                break

        if not modificado:
            messagebox.showwarning("Aviso", "No se encontró el registro original para modificar.", parent=win)
            return

        data["asignaciones_especiales"] = asignaciones
        guardar_config(data)
        recargar_grilla()
        limpiar_formulario()
        messagebox.showinfo("OK", "Asignación modificada correctamente.", parent=win)

    def eliminar():
        seleccion = tree.selection()
        if not seleccion:
            messagebox.showwarning("Atención", "Seleccioná una fila para eliminar.", parent=win)
            return

        iid = seleccion[0]
        idx = int(iid)

        visibles = getattr(tree, "asignaciones_visibles", [])
        if idx < 0 or idx >= len(visibles):
            messagebox.showerror("Error", "No se pudo recuperar la fila seleccionada.", parent=win)
            return

        a_eliminar = visibles[idx]

        ok = messagebox.askyesno(
            "Confirmar",
            f"¿Eliminar la asignación?\n\n"
            f"Legajo: {a_eliminar.get('legajo', '')}\n"
            f"Tipo: {a_eliminar.get('tipo', '')}\n"
            f"Desde: {a_eliminar.get('desde', '')}\n"
            f"Hasta: {a_eliminar.get('hasta', '')}",
            parent=win
        )
        if not ok:
            return

        data, asignaciones = obtener_asignaciones()

        nuevas = []
        eliminado = False

        for a in asignaciones:
            coincide = (
                str(a.get("legajo", "")).strip() == str(a_eliminar.get("legajo", "")).strip()
                and str(a.get("tipo", "")).strip().upper() == str(a_eliminar.get("tipo", "")).strip().upper()
                and str(a.get("desde", "")).strip() == str(a_eliminar.get("desde", "")).strip()
                and str(a.get("hasta", "")).strip() == str(a_eliminar.get("hasta", "")).strip()
                and str(a.get("inicio", "")).strip() == str(a_eliminar.get("inicio", "")).strip()
            )
            if coincide and not eliminado:
                eliminado = True
                continue
            nuevas.append(a)

        data["asignaciones_especiales"] = nuevas
        guardar_config(data)
        recargar_grilla()
        limpiar_formulario()

        if eliminado:
            messagebox.showinfo("OK", "Asignación eliminada correctamente.", parent=win)
        else:
            messagebox.showwarning("Aviso", "No se encontró el registro a eliminar.", parent=win)

    # -----------------------------
    # UI
    # -----------------------------
    tk.Label(
        win, text="ABM de Asignaciones Especiales",
        font=FONT_H2, bg=BG_WIN, fg=C_TITLE
    ).pack(pady=(12, 6))

    lbl_modo = tk.Label(win, text="Modo: Alta", font=FONT_BOLD, bg=BG_WIN, fg="#8a1c1c")
    lbl_modo.pack(pady=(0, 8))

    form = tk.Frame(win, bg=BG_FRAME, relief=tk.RIDGE, bd=2)
    form.pack(fill="x", padx=14, pady=8)

    tk.Label(form, text="Legajo",      bg=BG_FRAME, font=FONT_BASE).grid(row=0, column=0, padx=8, pady=6, sticky="e")
    entry_legajo = tk.Entry(form, width=18, font=FONT_BASE)
    entry_legajo.grid(row=0, column=1, padx=8, pady=6, sticky="w")

    tk.Label(form, text="Tipo",        bg=BG_FRAME, font=FONT_BASE).grid(row=0, column=2, padx=8, pady=6, sticky="e")
    combo_tipo = ttk.Combobox(form, values=["CORTADOR", "GUARDIA"], state="readonly", width=16)
    combo_tipo.grid(row=0, column=3, padx=8, pady=6, sticky="w")
    combo_tipo.set("CORTADOR")

    tk.Label(form, text="Desde",       bg=BG_FRAME, font=FONT_BASE).grid(row=1, column=0, padx=8, pady=6, sticky="e")
    entry_desde = tk.Entry(form, width=18, font=FONT_BASE)
    entry_desde.grid(row=1, column=1, padx=8, pady=6, sticky="w")

    tk.Label(form, text="Hasta",       bg=BG_FRAME, font=FONT_BASE).grid(row=1, column=2, padx=8, pady=6, sticky="e")
    entry_hasta = tk.Entry(form, width=18, font=FONT_BASE)
    entry_hasta.grid(row=1, column=3, padx=8, pady=6, sticky="w")

    tk.Label(form, text="Hora inicio", bg=BG_FRAME, font=FONT_BASE).grid(row=2, column=0, padx=8, pady=6, sticky="e")
    entry_hora = tk.Entry(form, width=18, font=FONT_BASE)
    entry_hora.grid(row=2, column=1, padx=8, pady=6, sticky="w")
    entry_hora.insert(0, "06:00")

    tk.Label(
        form,
        text="Formato fechas: YYYY-MM-DD    |    Hora: HH:MM",
        bg=BG_FRAME, fg=C_TITLE, font=("Segoe UI", 9, "italic")
    ).grid(row=2, column=2, columnspan=2, padx=8, pady=6, sticky="w")

    botones_form = tk.Frame(win, bg=BG_WIN)
    botones_form.pack(fill="x", padx=14, pady=(0, 8))

    tk.Button(botones_form, text="Guardar",   command=guardar,            bg=C_OK,   font=FONT_BOLD, width=14).pack(side="left", padx=5)
    tk.Button(botones_form, text="Modificar", command=cargar_seleccion,   bg=C_WARN, font=FONT_BOLD, width=14).pack(side="left", padx=5)
    tk.Button(botones_form, text="Eliminar",  command=eliminar,           bg=C_DEL,  font=FONT_BOLD, width=14).pack(side="left", padx=5)
    tk.Button(botones_form, text="Limpiar",   command=limpiar_formulario, bg=C_NEU,  font=FONT_BOLD, width=14).pack(side="left", padx=5)

    frame_grilla = tk.Frame(win, bg="#f2faff")
    frame_grilla.pack(fill="both", expand=True, padx=14, pady=8)

    columnas = ("legajo", "tipo", "desde", "hasta", "inicio")
    tree = ttk.Treeview(frame_grilla, columns=columnas, show="headings", height=14)

    tree.heading("legajo", text="Legajo")
    tree.heading("tipo", text="Tipo")
    tree.heading("desde", text="Desde")
    tree.heading("hasta", text="Hasta")
    tree.heading("inicio", text="Hora inicio")

    tree.column("legajo", width=120, anchor="center")
    tree.column("tipo", width=140, anchor="center")
    tree.column("desde", width=140, anchor="center")
    tree.column("hasta", width=140, anchor="center")
    tree.column("inicio", width=120, anchor="center")

    scroll_y = ttk.Scrollbar(frame_grilla, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll_y.set)

    tree.pack(side="left", fill="both", expand=True)
    scroll_y.pack(side="right", fill="y")

    tree.bind("<Double-1>", lambda e: cargar_seleccion())

    recargar_grilla()

def _accion_ver_resumen():
    global ULTIMOS_RESULTADOS_APLANADOS, ULTIMO_PERIODO_TEXTO

    if ULTIMOS_RESULTADOS_APLANADOS is None:
        messagebox.showwarning(
            "Atención",
            "Primero debés procesar un archivo (Cargar archivo de fichadas).",
            parent=ventana
        )
        return

    if not RESUMEN_ESTADISTICO_DISPONIBLE:
        messagebox.showwarning(
            "Atención",
            "No está disponible resumen_estadistico.py.",
            parent=ventana
        )
        return

    try:
        resumen = generar_resumen(ULTIMOS_RESULTADOS_APLANADOS)
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo calcular el resumen:\n{e}", parent=ventana)
        return

    if not RESUMEN_UI_DISPONIBLE:
        messagebox.showwarning(
            "Resumen en pantalla no disponible",
            "El resumen estadístico se calculó OK, pero no se pudo abrir la ventana.\n\n"
            f"Motivo:\n{RESUMEN_UI_ERROR}",
            parent=ventana
        )
        return

    try:
        mostrar_resumen(resumen, CARPETA_REPORTES, (ULTIMO_PERIODO_TEXTO or "Período"), parent=ventana)
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo abrir la ventana de resumen:\n{e}", parent=ventana)

# =============================================================================
# FLUJO PRINCIPAL
# =============================================================================
def cargar_archivo():
    global ULTIMOS_RESULTADOS_APLANADOS, ULTIMO_PERIODO_TEXTO, ULTIMO_ARCHIVO

    archivos_disp = [f for f in os.listdir(CARPETA_ARCHIVOS) if f.endswith((".xlsx", ".csv"))]
    if not archivos_disp:
        messagebox.showwarning("Atención", f"No se encontraron archivos .xlsx o .csv en:\n{CARPETA_ARCHIVOS}", parent=ventana)
        return

    archivo = seleccionar_archivo_con_fecha(archivos_disp, CARPETA_ARCHIVOS, parent=ventana)
    if not archivo or archivo not in archivos_disp:
        messagebox.showwarning("Atención", "No se seleccionó un archivo válido.", parent=ventana)
        return

    ULTIMO_ARCHIVO = archivo
    ruta_archivo = os.path.join(CARPETA_ARCHIVOS, archivo)

    try:
        # Carga flexible: si es CSV, probar ; y luego ,
        if ruta_archivo.lower().endswith(".csv"):
            try:
                df = pd.read_csv(ruta_archivo, encoding="utf-8", sep=";")
                if df.shape[1] < 3:
                    df = pd.read_csv(ruta_archivo, encoding="utf-8", sep=",")
            except Exception:
                df = pd.read_csv(ruta_archivo, encoding="utf-8", sep=",")
        else:
            df = pd.read_excel(ruta_archivo)

        # Mapeo columnas del reloj → internas
        mapeo_columnas = {
            "Nro. de usuario": "Legajo",
            "Fecha/Hora": "FechaHora",
            "Tipo de registro": "Tipo",
            "Nombre": "Nombre",
            "Departamento": "Departamento"
        }
        df.rename(columns=mapeo_columnas, inplace=True)

        columnas_necesarias = {"Legajo", "FechaHora", "Tipo"}
        if not columnas_necesarias.issubset(df.columns):
            messagebox.showerror("Error", f"El archivo debe contener las columnas:\n{columnas_necesarias}", parent=ventana)
            return

        # Completar Nombre/Departamento hacia adelante
        for col in ["Nombre", "Departamento"]:
            if col in df.columns:
                df[col] = df[col].ffill()

        df["FechaHora"] = pd.to_datetime(df["FechaHora"], errors="coerce")

        # Mes (o rango) para el PDF
        MESES_ES = {
            1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
            5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
            9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
        }
        min_fecha = df["FechaHora"].min()
        max_fecha = df["FechaHora"].max()

        mes_ini, anio_ini = MESES_ES[min_fecha.month], int(min_fecha.year)
        mes_fin, anio_fin = MESES_ES[max_fecha.month], int(max_fecha.year)

        mes_completo = (
            f"{mes_ini} {anio_ini}"
            if (mes_ini, anio_ini) == (mes_fin, anio_fin)
            else f"{mes_ini} {anio_ini} - {mes_fin} {anio_fin}"
        )
        ULTIMO_PERIODO_TEXTO = mes_completo

        # Procesamiento con entrada inteligente
        resultados = procesar_fichadas(df,inicio_variable=INICIO_VARIABLE,excluir_tardanza=EXCLUIR_TARDANZA)

        resultados_aplanados = aplanar_registros_por_tramo(resultados)

        # Guardar para menú Ver → Resumen/Gráficos
        ULTIMOS_RESULTADOS_APLANADOS = resultados_aplanados

        # Vista previa
        mostrar_detallado_en_pantalla(resultados_aplanados, parent=ventana)

        # PDFs (tu lógica original, sin romper)
        ruta_pdf = os.path.join(CARPETA_REPORTES, "reporte_fichadas.pdf")
        ruta_resumen = os.path.join(CARPETA_REPORTES, "reporte_resumen.pdf")

        feriados = set(cargar_feriados())
        grosor_lunes = 0.7

        _sig_gen = dict(inspect.signature(generar_pdf_general).parameters)
        if 'feriados' in _sig_gen and 'grosor_lunes' in _sig_gen:
            generar_pdf_general(
                resultados_aplanados,
                mes=mes_completo,
                salida=ruta_pdf,
                feriados=feriados,
                grosor_lunes=grosor_lunes
            )
        else:
            generar_pdf_general(
                resultados_aplanados,
                mes=mes_completo,
                salida=ruta_pdf
            )

        _sig_res = dict(inspect.signature(generar_pdf_resumen).parameters)
        if 'feriados' in _sig_res and 'grosor_lunes' in _sig_res:
            generar_pdf_resumen(
                resultados_aplanados,
                mes=mes_completo,
                salida=ruta_resumen,
                feriados=feriados,
                grosor_lunes=grosor_lunes
            )
        else:
            generar_pdf_resumen(
                resultados_aplanados,
                mes=mes_completo,
                salida=ruta_resumen
            )

        # Resumen estadístico (si está tildado)
        resumen_generado = False
        if RESUMEN_ESTADISTICO_DISPONIBLE and var_resumen.get():
            try:
                resumen = generar_resumen(resultados_aplanados)
                resumen_generado = True

                if RESUMEN_UI_DISPONIBLE:
                    mostrar_resumen(resumen, CARPETA_REPORTES, mes_completo, parent=ventana)
                else:
                    messagebox.showwarning(
                        "Resumen en pantalla no disponible",
                        "El resumen estadístico se calculó OK, pero no se pudo abrir la ventana.\n\n"
                        f"Motivo:\n{RESUMEN_UI_ERROR}",
                        parent=ventana
                    )
            except Exception as e:
                messagebox.showwarning("Aviso", f"No se pudo generar el resumen estadístico (opcional):\n{e}", parent=ventana)

        extra = "\n• Resumen estadístico: OK" if resumen_generado else ""
        messagebox.showinfo(
            "Éxito",
            f"Se generaron los informes correctamente:\n\n• {ruta_pdf}\n• {ruta_resumen}{extra}",
            parent=ventana
        )

    except Exception as e:
        messagebox.showerror("Error", str(e), parent=ventana)

# =============================================================================
# UI
# =============================================================================
ventana = tk.Tk()
ventana.title(f"CM_HorasExtras v{get_version()}")
ventana.geometry("480x490")
ventana.resizable(False, False)
ventana.configure(bg=BG_WIN)

# ─── Tema ttk global ────────────────────────────────────────────────────────
_style = ttk.Style()
try:
    _style.theme_use("vista")
except Exception:
    try:
        _style.theme_use("clam")
    except Exception:
        pass
_style.configure("Treeview",        rowheight=26, font=FONT_BASE)
_style.configure("Treeview.Heading", font=FONT_BOLD, background=BG_FRAME)
_style.map("Treeview",
           background=[("selected", C_PRI)],
           foreground=[("selected", C_TITLE)])
_style.configure("TCombobox", font=FONT_BASE)

# Ícono de la ventana (prioridad: recursos/logo.ico)
try:
    if os.path.exists(ICON_ICO):
        ventana.iconbitmap(ICON_ICO)
except Exception:
    pass

# Fallback iconphoto si hay PNG (Tk usa PhotoImage)
try:
    if os.path.exists(ICON_PNG):
        ventana.iconphoto(True, tk.PhotoImage(file=ICON_PNG))
except Exception:
    pass

# =========================================================
# MENÚ SUPERIOR
# =========================================================
menubar = tk.Menu(ventana)
ventana.config(menu=menubar)

# -------------------------
# ARCHIVO
# -------------------------
menu_archivo = tk.Menu(menubar, tearoff=0)
menubar.add_cascade(label="Archivo", menu=menu_archivo)

menu_archivo.add_command(
    label="Cargar archivo de fichadas…",
    command=cargar_archivo
)

menu_archivo.add_separator()

menu_archivo.add_command(
    label="Gestionar feriados…",
    command=_accion_gestionar_feriados
)

menu_archivo.add_separator()

menu_archivo.add_command(
    label="Salir",
    command=_accion_salir
)

# -------------------------
# VER
# -------------------------
menu_ver = tk.Menu(menubar, tearoff=0)
menubar.add_cascade(label="Ver", menu=menu_ver)

menu_ver.add_command(
    label="Resumen estadístico…",
    command=_accion_ver_resumen
)

menu_ver.add_command(
    label="Gráficos…",
    command=_accion_ver_graficos
)

# -------------------------
# OPERATIVO
# -------------------------
menu_operativo = tk.Menu(menubar, tearoff=0)
menubar.add_cascade(label="Operativo", menu=menu_operativo)

menu_operativo.add_command(
    label="Asignaciones cortadores…",
    command=abrir_gestor_asignaciones_especiales
)

menu_operativo.add_separator()

menu_operativo.add_command(
    label="Horarios Base Paro…",
    command=abrir_gestor_horarios_paro
)
menu_operativo.add_command(
    label="Gestionar Días de Paro…",
    command=abrir_gestor_dias_paro
)
# ── Label de versión (reserva espacio desde abajo primero) ──────────────────
tk.Label(ventana, text=f"v{get_version()}", font=FONT_SM, bg=BG_WIN, fg="#aaaaaa"
).pack(side="bottom", pady=(0, 4))

# ── Logo + título ────────────────────────────────────────────────────────────
try:
    if os.path.exists(LOGO_PATH):
        logo_img = Image.open(LOGO_PATH)
        logo_img = logo_img.resize((72, 72))
        logo_tk = ImageTk.PhotoImage(logo_img)
        logo_label = tk.Label(ventana, image=logo_tk, bg=BG_WIN)
        logo_label.image = logo_tk
        logo_label.pack(pady=(12, 2))

    app_title = tk.Label(ventana, text="CM La Paz Online",
                         font=FONT_TITLE, bg=BG_WIN, fg=C_TITLE)
    app_title.pack(pady=(2, 2))
except Exception:
    app_title = tk.Label(ventana, text="CM La Paz Online",
                         font=FONT_TITLE, bg=BG_WIN, fg=C_TITLE)
    app_title.pack(pady=(18, 2))

tk.Label(ventana, text="Sistema de Control de Horas Extras",
         font=FONT_BASE, bg=BG_WIN, fg=C_TITLE).pack(pady=(0, 8))

# ── Marco central ────────────────────────────────────────────────────────────
marco = tk.Frame(ventana, bg=BG_FRAME, relief=tk.RIDGE, bd=2)
marco.pack(padx=24, pady=4, fill="x")

var_resumen = tk.BooleanVar(value=False)
chk_resumen = tk.Checkbutton(
    marco, text="Generar informe estadístico del período",
    variable=var_resumen, font=FONT_BASE,
    bg=BG_FRAME, fg="black", activebackground=BG_FRAME
)
if not RESUMEN_ESTADISTICO_DISPONIBLE:
    chk_resumen.configure(state="disabled")
chk_resumen.pack(pady=(8, 4))

tk.Button(
    marco, text="Cargar archivo de fichadas",
    command=cargar_archivo,
    font=("Segoe UI", 12, "bold"),
    bg=C_PRI, fg="black", width=26, height=2
).pack(pady=(2, 8))

tk.Button(
    marco, text="Gestionar feriados",
    command=abrir_gestor_feriados,
    font=FONT_BASE,
    bg=C_OK, fg="black", width=22
).pack(pady=(0, 10))

tk.Button(
    marco, text="🌐  Confirmaciones web",
    command=lambda: webbrowser.open("https://cmhoras.pythonanywhere.com"),
    font=FONT_BASE,
    bg="#dbeafe", fg="#1e3a5f", width=22
).pack(pady=(0, 6))

# ── Salir ────────────────────────────────────────────────────────────────────
def _salir():
    ventana.destroy()

tk.Button(
    ventana, text="Salir del sistema",
    command=_salir,
    font=FONT_BOLD, bg=C_DEL, fg="black", width=18
).pack(pady=(8, 6))

ventana.mainloop()
