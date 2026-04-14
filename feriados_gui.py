import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox, simpledialog
from datetime import datetime
import json
import os

CONFIG_PATH = "config.json"

_F      = "Segoe UI"
_BG     = "#f2faff"
_FRAME  = "#e7f5ff"
_TITLE  = "#1a435b"
_C_PRI  = "#71c7ec"
_C_OK   = "#afe9b7"
_C_DEL  = "#f4978e"
_C_NEU  = "#d9eaf7"

def cargar_feriados():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            feriados_raw = json.load(f).get("feriados", [])
        # Asegura formato string yyyy-mm-dd al cargar
        feriados = [
            d.strftime("%Y-%m-%d") if isinstance(d, datetime) else str(d)[:10]
            for d in feriados_raw
        ]
        return feriados
    return []

def guardar_feriados(feriados):
    feriados = sorted(list(set(feriados)))
    # Leer config completo para no destruir otras claves (asignaciones_especiales,
    # dias_paro, horarios_paro, etc.)
    config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    config["feriados"] = feriados
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def abrir_gestor_feriados():
    ventana = tk.Toplevel()
    ventana.title("Gestionar feriados")
    ventana.geometry("400x360")
    ventana.configure(bg=_BG)
    ventana.resizable(False, False)

    tk.Label(
        ventana, text="Feriados configurados",
        font=(_F, 13, "bold"), bg=_BG, fg=_TITLE
    ).pack(pady=(10, 4))

    frm = tk.Frame(ventana, bg=_BG)
    frm.pack(expand=True, fill="both", padx=14, pady=2)

    sb = ttk.Scrollbar(frm, orient="vertical")
    lista = tk.Listbox(
        frm, font=(_F, 10), height=12,
        yscrollcommand=sb.set, selectbackground=_C_PRI,
        relief=tk.FLAT, bd=1, highlightthickness=1
    )
    sb.config(command=lista.yview)

    feriados = cargar_feriados()
    for fecha in feriados:
        lista.insert(tk.END, fecha)

    lista.pack(side="left", expand=True, fill="both")
    sb.pack(side="right", fill="y")

    def agregar():
        nueva_fecha = simpledialog.askstring(
            "Agregar feriado", "Ingrese fecha (YYYY-MM-DD):", parent=ventana
        )
        if nueva_fecha:
            nueva_fecha = nueva_fecha.strip()
            try:
                datetime.strptime(nueva_fecha, "%Y-%m-%d")
                if nueva_fecha not in feriados:
                    feriados.append(nueva_fecha)
                    lista.insert(tk.END, nueva_fecha)
                    guardar_feriados(feriados)
                else:
                    messagebox.showinfo("Ya existe", "Ese feriado ya está cargado.", parent=ventana)
            except ValueError:
                messagebox.showerror("Error", "Formato incorrecto. Use YYYY-MM-DD.", parent=ventana)

    def eliminar():
        seleccion = lista.curselection()
        if seleccion:
            idx = seleccion[0]
            fecha = lista.get(idx)
            feriados.remove(fecha)
            lista.delete(idx)
            guardar_feriados(feriados)
        else:
            messagebox.showwarning("Atención", "Seleccioná un feriado de la lista.", parent=ventana)

    # Todos los botones en una sola fila
    btn_frm = tk.Frame(ventana, bg=_BG)
    btn_frm.pack(pady=8)

    tk.Button(btn_frm, text="Agregar",  command=agregar,          font=(_F, 10, "bold"), bg=_C_OK,  width=12).pack(side="left", padx=5)
    tk.Button(btn_frm, text="Eliminar", command=eliminar,         font=(_F, 10, "bold"), bg=_C_DEL, width=12).pack(side="left", padx=5)
    tk.Button(btn_frm, text="Cerrar",   command=ventana.destroy,  font=(_F, 10),         bg=_C_NEU, width=10).pack(side="left", padx=5)

    ventana.transient()
    ventana.grab_set()
    ventana.focus_set()
