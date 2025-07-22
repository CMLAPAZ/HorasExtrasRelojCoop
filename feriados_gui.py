import tkinter as tk
from tkinter import messagebox, simpledialog
from datetime import datetime
import json
import os

CONFIG_PATH = "config.json"

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
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"feriados": feriados}, f, indent=2, ensure_ascii=False)

def abrir_gestor_feriados():
    ventana = tk.Toplevel()
    ventana.title("Gestionar feriados")
    ventana.geometry("350x300")

    feriados = cargar_feriados()

    lista = tk.Listbox(ventana, font=("Arial", 11))
    lista.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
    for fecha in feriados:
        lista.insert(tk.END, fecha)

    def agregar():
        nueva_fecha = simpledialog.askstring("Agregar feriado", "Ingrese fecha (YYYY-MM-DD):", parent=ventana)
        if nueva_fecha:
            nueva_fecha = nueva_fecha.strip()
            try:
                datetime.strptime(nueva_fecha, "%Y-%m-%d")  # Validar formato
                if nueva_fecha not in feriados:
                    feriados.append(nueva_fecha)
                    lista.insert(tk.END, nueva_fecha)
                    guardar_feriados(feriados)
                else:
                    messagebox.showinfo("Ya existe", "Ese feriado ya está cargado.")
            except ValueError:
                messagebox.showerror("Error", "Formato incorrecto. Use YYYY-MM-DD.")

    def eliminar():
        seleccion = lista.curselection()
        if seleccion:
            idx = seleccion[0]
            fecha = lista.get(idx)
            feriados.remove(fecha)
            lista.delete(idx)
            guardar_feriados(feriados)

    boton_agregar = tk.Button(ventana, text="Agregar feriado", command=agregar)
    boton_agregar.pack(pady=5)

    boton_eliminar = tk.Button(ventana, text="Eliminar seleccionado", command=eliminar)
    boton_eliminar.pack(pady=5)

    boton_cerrar = tk.Button(ventana, text="Cerrar", command=ventana.destroy)
    boton_cerrar.pack(pady=5)

    ventana.transient()
    ventana.grab_set()
    ventana.focus_set()
