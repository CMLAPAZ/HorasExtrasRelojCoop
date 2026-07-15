# -*- coding: utf-8 -*-
"""
puntualidad_ui.py - Ventana independiente para Control de Puntualidad.

No se integra a main.py. Se ejecuta aparte:
    python puntualidad_ui.py
"""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from puntualidad_db import consultar_jornadas_mes, consultar_resumen_mes
from puntualidad_importador import importar_archivo_puntualidad


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARPETA_ARCHIVOS = os.path.join(BASE_DIR, "archivos")


def _mes_actual():
    import datetime
    hoy = datetime.date.today()
    return hoy.year, hoy.month


class PuntualidadApp:
    def __init__(self, root):
        self.root = root
        self.ruta_archivo = None

        root.title("Control de Puntualidad")
        root.geometry("1080x650")
        root.minsize(960, 560)

        self.archivo_var = tk.StringVar(value="Sin archivo seleccionado")
        anio, mes = _mes_actual()
        self.anio_var = tk.StringVar(value=str(anio))
        self.mes_var = tk.IntVar(value=mes)
        self.depto_var = tk.StringVar(value="Todos")
        self.desde_var = tk.StringVar(value="")
        self.hasta_var = tk.StringVar(value="")
        self.reemplazar_var = tk.BooleanVar(value=False)
        self.estado_var = tk.StringVar(value="Listo")

        self._crear_ui()
        self.cargar_resumen()

    def _crear_ui(self):
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=10)

        tab_importar = ttk.Frame(self.tabs)
        tab_consultar = ttk.Frame(self.tabs)
        self.tabs.add(tab_importar, text="Importar")
        self.tabs.add(tab_consultar, text="Consultar")

        import_box = ttk.LabelFrame(tab_importar, text="Importar fichadas")
        import_box.pack(fill="x", padx=12, pady=12)

        ttk.Label(import_box, textvariable=self.archivo_var).grid(
            row=0, column=0, columnspan=6, sticky="w", padx=8, pady=(6, 2)
        )
        ttk.Button(import_box, text="Seleccionar archivo", command=self.seleccionar_archivo).grid(
            row=1, column=0, padx=8, pady=6, sticky="w"
        )
        ttk.Label(import_box, text="Desde").grid(row=1, column=1, padx=(8, 2), pady=6)
        ttk.Entry(import_box, textvariable=self.desde_var, width=12).grid(row=1, column=2, pady=6)
        ttk.Label(import_box, text="Hasta").grid(row=1, column=3, padx=(8, 2), pady=6)
        ttk.Entry(import_box, textvariable=self.hasta_var, width=12).grid(row=1, column=4, pady=6)
        ttk.Checkbutton(import_box, text="Recalcular mes", variable=self.reemplazar_var).grid(
            row=2, column=0, padx=8, pady=(0, 8), sticky="w"
        )
        ttk.Button(import_box, text="Importar", command=self.importar).grid(
            row=2, column=1, padx=8, pady=(0, 8), sticky="w"
        )
        import_box.columnconfigure(5, weight=1)

        ayuda = (
            "La importacion guarda los datos en datos/puntualidad.db. "
            "Si marcas Recalcular mes, se reemplazan los datos del mes importado."
        )
        ttk.Label(tab_importar, text=ayuda, wraplength=760, justify="left").pack(
            anchor="w", padx=16, pady=(0, 12)
        )

        filtro_box = ttk.LabelFrame(tab_consultar, text="Filtros")
        filtro_box.pack(fill="x", padx=12, pady=12)

        ttk.Label(filtro_box, text="Anio").grid(row=0, column=0, padx=(8, 2), pady=10)
        ttk.Entry(filtro_box, textvariable=self.anio_var, width=8).grid(row=0, column=1, pady=10)
        ttk.Label(filtro_box, text="Mes").grid(row=0, column=2, padx=(8, 2), pady=10)
        ttk.Combobox(
            filtro_box,
            textvariable=self.mes_var,
            values=list(range(1, 13)),
            width=5,
            state="readonly",
        ).grid(row=0, column=3, pady=10)
        ttk.Label(filtro_box, text="Depto").grid(row=0, column=4, padx=(8, 2), pady=10)
        ttk.Combobox(
            filtro_box,
            textvariable=self.depto_var,
            values=["Todos", "redes", "administracion"],
            width=16,
            state="readonly",
        ).grid(row=0, column=5, pady=10)
        ttk.Button(filtro_box, text="Cargar", command=self.cargar_resumen).grid(
            row=0, column=6, padx=8, pady=10
        )
        filtro_box.columnconfigure(7, weight=1)

        paned = ttk.PanedWindow(tab_consultar, orient="vertical")
        paned.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        resumen_frame = ttk.Frame(paned)
        detalle_frame = ttk.Frame(paned)
        paned.add(resumen_frame, weight=3)
        paned.add(detalle_frame, weight=2)

        self.tree_resumen = self._crear_tree(
            resumen_frame,
            ("departamento", "legajo", "nombre", "dias", "tardanzas", "minutos", "estado"),
            {
                "departamento": ("Departamento", 130),
                "legajo": ("Legajo", 80),
                "nombre": ("Nombre", 280),
                "dias": ("Dias eval.", 90),
                "tardanzas": ("Tardanzas", 90),
                "minutos": ("Minutos", 80),
                "estado": ("Estado", 120),
            },
        )
        self.tree_resumen.bind("<<TreeviewSelect>>", lambda _e: self.cargar_detalle())

        self.tree_detalle = self._crear_tree(
            detalle_frame,
            ("fecha", "programada", "entrada", "minutos", "estado", "observacion"),
            {
                "fecha": ("Fecha", 110),
                "programada": ("Prog.", 80),
                "entrada": ("Entrada", 80),
                "minutos": ("Min.", 70),
                "estado": ("Estado", 130),
                "observacion": ("Observacion", 520),
            },
        )

        ttk.Label(self.root, textvariable=self.estado_var, anchor="w").pack(
            fill="x", padx=12, pady=(0, 8)
        )

    def _crear_tree(self, parent, columnas, meta):
        tree = ttk.Treeview(parent, columns=columnas, show="headings")
        scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        for col in columnas:
            titulo, ancho = meta[col]
            tree.heading(col, text=titulo)
            tree.column(col, width=ancho, anchor="center")
        if "nombre" in columnas:
            tree.column("nombre", anchor="w")
        if "observacion" in columnas:
            tree.column("observacion", anchor="w")
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return tree

    def _filtros(self):
        anio = int(self.anio_var.get().strip())
        mes = int(self.mes_var.get())
        depto = self.depto_var.get()
        return anio, mes, None if depto == "Todos" else depto

    def _limpiar(self, tree):
        for item in tree.get_children():
            tree.delete(item)

    def seleccionar_archivo(self):
        ruta = filedialog.askopenfilename(
            parent=self.root,
            initialdir=CARPETA_ARCHIVOS if os.path.isdir(CARPETA_ARCHIVOS) else BASE_DIR,
            title="Seleccionar fichadas",
            filetypes=[
                ("Fichadas", "*.xlsx *.xls *.csv"),
                ("Excel", "*.xlsx *.xls"),
                ("CSV", "*.csv"),
                ("Todos", "*.*"),
            ],
        )
        if ruta:
            self.ruta_archivo = ruta
            self.archivo_var.set(os.path.basename(ruta))

    def importar(self):
        if not self.ruta_archivo:
            messagebox.showwarning("Atención", "Seleccioná un archivo primero.", parent=self.root)
            return
        try:
            res = importar_archivo_puntualidad(
                BASE_DIR,
                self.ruta_archivo,
                fecha_desde=self.desde_var.get().strip() or None,
                fecha_hasta=self.hasta_var.get().strip() or None,
                reemplazar_mes=self.reemplazar_var.get(),
            )
            if res.get("periodo_desde"):
                self.anio_var.set(res["periodo_desde"][:4])
                self.mes_var.set(int(res["periodo_desde"][5:7]))
            self.estado_var.set(
                f"Importado: {res['jornadas_guardadas']} jornadas, "
                f"{res['resumenes_guardados']} resumenes"
            )
            self.cargar_resumen()
            self.tabs.select(1)
            messagebox.showinfo("OK", "Importacion finalizada.", parent=self.root)
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self.root)

    def cargar_resumen(self):
        try:
            anio, mes, depto = self._filtros()
            rows = consultar_resumen_mes(BASE_DIR, anio, mes, departamento=depto)
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self.root)
            return

        self._limpiar(self.tree_resumen)
        self._limpiar(self.tree_detalle)
        for r in rows:
            self.tree_resumen.insert("", "end", values=(
                r["departamento"],
                r["legajo"],
                r["nombre"],
                r["dias_evaluados"],
                r["cantidad_tardanzas"],
                r["minutos_tarde"],
                r["estado_mensual"],
            ))
        self.estado_var.set(f"Resumen cargado: {len(rows)} empleados")

    def cargar_detalle(self):
        sel = self.tree_resumen.selection()
        if not sel:
            return
        vals = self.tree_resumen.item(sel[0], "values")
        legajo = vals[1]
        try:
            anio, mes, depto = self._filtros()
            rows = consultar_jornadas_mes(BASE_DIR, anio, mes, departamento=depto, legajo=legajo)
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self.root)
            return

        self._limpiar(self.tree_detalle)
        for r in rows:
            self.tree_detalle.insert("", "end", values=(
                r["fecha"],
                r["hora_programada"] or "",
                r["hora_entrada"] or "",
                r["minutos_tarde"],
                r["estado_jornada"],
                r["observacion"] or "",
            ))
        self.estado_var.set(f"Detalle cargado: legajo {legajo}, {len(rows)} jornadas")


def main():
    root = tk.Tk()
    PuntualidadApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
