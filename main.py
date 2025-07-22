import tkinter as tk
from tkinter import messagebox
import tkinter.ttk as ttk
from PIL import Image, ImageTk
import pandas as pd
from procesador import procesar_fichadas, aplanar_registros_por_tramo
from pdf_generator import PDFGeneral, generar_pdf_general, generar_pdf_resumen
from feriados_gui import abrir_gestor_feriados
import os
from datetime import timedelta
import datetime

# Directorios fijos del sistema
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARPETA_ARCHIVOS = os.path.join(BASE_DIR, "archivos")
CARPETA_REPORTES = os.path.join(BASE_DIR, "reportes")
CARPETA_LOGO = os.path.join(BASE_DIR, "logo")
LOGO_PATH = os.path.join(CARPETA_LOGO, "logo.png")

os.makedirs(CARPETA_ARCHIVOS, exist_ok=True)
os.makedirs(CARPETA_REPORTES, exist_ok=True)
os.makedirs(CARPETA_LOGO, exist_ok=True)

# ------ Selector visual de archivos con fecha de modificación ------
def seleccionar_archivo_con_fecha(archivos_disp, carpeta):
    win = tk.Toplevel()
    win.title("Seleccionar archivo a procesar")
    win.geometry("650x370")
    label = tk.Label(win, text="Seleccioná un archivo de la lista:", font=("Arial", 12))
    label.pack(pady=8)
    lista = tk.Listbox(win, font=("Arial", 11), height=14)
    archivos_mostrados = []
    for f in archivos_disp:
        ruta_f = os.path.join(carpeta, f)
        fecha = os.path.getmtime(ruta_f)
        fecha_fmt = datetime.datetime.fromtimestamp(fecha).strftime('%d/%m/%Y %H:%M')
        label_f = f"{f}   (últ. modif: {fecha_fmt})"
        archivos_mostrados.append((f, label_f, fecha))
        lista.insert(tk.END, label_f)
    lista.pack(expand=True, fill="both", padx=20)
    seleccionado = {"nombre": None}
    def confirmar():
        try:
            idx = lista.curselection()[0]
            seleccionado["nombre"] = archivos_mostrados[idx][0]
            win.destroy()
        except IndexError:
            messagebox.showwarning("Atención", "Seleccioná un archivo.")
    btn = tk.Button(win, text="Procesar archivo seleccionado", command=confirmar, font=("Arial", 12), bg="#71c7ec")
    btn.pack(pady=10)
    win.transient()
    win.grab_set()
    win.wait_window()
    return seleccionado["nombre"]

# ------ Mostrar DETALLADO por pantalla (mejorado y corregido) ------
def mostrar_detallado_en_pantalla(data):
    win = tk.Toplevel()
    win.title("Detalle de Fichadas por Empleado")
    win.geometry("1220x520")
    columnas = ["Legajo", "Nombre", "Fecha", "Entrada", "Salida", "Normales", "50%", "100%", "Tarde", "FRANCO", "COMIDA", "Observaciones"]
    tree = ttk.Treeview(win, columns=columnas, show="headings", height=20)
    for col in columnas:
        tree.heading(col, text=col)
        ancho = 100 if col not in ("Nombre", "Observaciones") else (180 if col == "Nombre" else 240)
        tree.column(col, width=ancho, anchor='center')
    tree.pack(expand=True, fill="both")

    for emp in data:
        legajo = emp.get("legajo", "")
        nombre = emp.get("nombre", "")
        registros = emp.get("registros", [])
        for r in registros:
            # Resaltar SOLO la última fila del día (si tiene algún total >0 o hay observaciones)
            es_ultima = (
                (isinstance(r.get("Normales"), timedelta) and r.get("Normales").total_seconds() > 0) or
                (isinstance(r.get("50%"), timedelta) and r.get("50%").total_seconds() > 0) or
                (isinstance(r.get("100%"), timedelta) and r.get("100%").total_seconds() > 0) or
                (isinstance(r.get("Tarde"), int) and r.get("Tarde") > 0) or
                (isinstance(r.get("FRANCO"), int) and r.get("FRANCO") > 0) or
                (isinstance(r.get("COMIDA"), int) and r.get("COMIDA") > 0) or
                (isinstance(r.get("Observaciones"), str) and r.get("Observaciones"))
            )
            tags = ("ultimo",) if es_ultima else ()
            tree.insert("", "end", values=[
                legajo,
                nombre,
                r.get("Fecha", ""),
                r.get("Entrada", ""),
                r.get("Salida", ""),
                r.get("Normales", ""),
                r.get("50%", ""),
                r.get("100%", ""),
                r.get("Tarde", ""),
                r.get("FRANCO", ""),
                r.get("COMIDA", ""),
                r.get("Observaciones", "")
            ], tags=tags)
    tree.tag_configure("ultimo", font=("Arial", 9, "bold"), background="#eaffea")
    win.transient()
    win.grab_set()
    win.wait_window()

# ------ Función principal ------
def cargar_archivo():
    archivos_disp = [f for f in os.listdir(CARPETA_ARCHIVOS) if f.endswith((".xlsx", ".csv"))]
    if not archivos_disp:
        messagebox.showwarning("Atención", f"No se encontraron archivos .xlsx o .csv en: {CARPETA_ARCHIVOS}")
        return

    archivo = seleccionar_archivo_con_fecha(archivos_disp, CARPETA_ARCHIVOS)
    if not archivo or archivo not in archivos_disp:
        messagebox.showwarning("Atención", "No se seleccionó un archivo válido.")
        return

    ruta_archivo = os.path.join(CARPETA_ARCHIVOS, archivo)
    try:
        df = pd.read_excel(ruta_archivo)
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
            messagebox.showerror("Error", f"El archivo debe contener las columnas: {columnas_necesarias}")
            return
        for col in ["Nombre", "Departamento"]:
            if col in df.columns:
                df[col] = df[col].fillna(method="ffill")
        df["FechaHora"] = pd.to_datetime(df["FechaHora"])
        MESES_ES = {
            1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
            5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
            9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
        }
        min_fecha = df["FechaHora"].min()
        max_fecha = df["FechaHora"].max()
        mes_ini = MESES_ES[min_fecha.month]
        anio_ini = min_fecha.year
        mes_fin = MESES_ES[max_fecha.month]
        anio_fin = max_fecha.year
        if (mes_ini, anio_ini) == (mes_fin, anio_fin):
            mes_completo = f"{mes_ini} {anio_ini}"
        else:
            mes_completo = f"{mes_ini} {anio_ini} - {mes_fin} {anio_fin}"
        resultados = procesar_fichadas(df)
        resultados = aplanar_registros_por_tramo(resultados)
        mostrar_detallado_en_pantalla(resultados)
        ruta_pdf = os.path.join(CARPETA_REPORTES, "reporte_fichadas.pdf")
        ruta_resumen = os.path.join(CARPETA_REPORTES, "reporte_resumen.pdf")
        generar_pdf_general(resultados, mes=mes_completo, salida=ruta_pdf)
        print(f"✅ PDF general generado: {ruta_pdf}")
        generar_pdf_resumen(resultados, mes=mes_completo, salida=ruta_resumen)
        print(f"✅ PDF resumen generado: {ruta_resumen}")
        messagebox.showinfo(
            "Éxito",
            f"Se generaron los informes correctamente:\n\n• {ruta_pdf}\n• {ruta_resumen}"
        )
    except Exception as e:
        messagebox.showerror("Error", str(e))

# --- INTERFAZ VISUAL ---
ventana = tk.Tk()
ventana.title("CM_HorasExtras - Sistema de Fichadas")
ventana.geometry("510x440")
ventana.configure(bg="#f2faff")  # Celeste muy suave

# --- LOGO + TÍTULO ---
try:
    logo_img = Image.open(LOGO_PATH)
    logo_img = logo_img.resize((100, 100))
    logo_tk = ImageTk.PhotoImage(logo_img)
    logo_label = tk.Label(ventana, image=logo_tk, bg="#f2faff")
    logo_label.pack(pady=(14, 3))
    app_title = tk.Label(ventana, text="CM La Paz Online", font=("Arial", 19, "bold"), bg="#f2faff", fg="#1a435b")
    app_title.pack(pady=(2, 10))
except Exception as e:
    app_title = tk.Label(ventana, text="CM La Paz Online", font=("Arial", 22, "bold"), bg="#f2faff", fg="#1a435b")
    app_title.pack(pady=(22, 10))

welcome = tk.Label(ventana, text="Bienvenida/o al Sistema de Control de Horas Extras del Reloj", font=("Arial", 13, "bold"), bg="#f2faff", fg="#1a435b")
welcome.pack(pady=(5, 10))

marco = tk.Frame(ventana, bg="#e7f5ff", relief=tk.RIDGE, bd=3)
marco.pack(padx=20, pady=10, fill="both", expand=False)

boton = tk.Button(marco, text="Cargar archivo de fichadas", command=cargar_archivo, font=("Arial", 13), bg="#71c7ec", fg="black", width=24, height=2)
boton.pack(pady=20)

btn_feriados = tk.Button(marco, text="Gestionar feriados", command=abrir_gestor_feriados, font=("Arial", 12), bg="#afe9b7", fg="black", width=24, height=1)
btn_feriados.pack(pady=10)

btn_salir = tk.Button(ventana, text="Salir del sistema", command=ventana.destroy, font=("Arial", 11, "bold"), bg="#f4978e", fg="black", width=18)
btn_salir.pack(pady=18)

ventana.mainloop()

