# -*- coding: utf-8 -*-
"""
puntualidad_ui.py - Ventana independiente para Control de Puntualidad.

No se integra a main.py. Se ejecuta aparte:
    python puntualidad_ui.py
"""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from puntualidad_db import (
    consultar_acumulado_anual,
    consultar_jornadas_mes,
    consultar_resumen_rango,
    consultar_resumen_mes,
    consultar_tardanzas,
    desjustificar_jornada,
    inicializar_base_puntualidad,
    justificar_jornada,
)
from puntualidad_importador import importar_archivo_puntualidad, recalcular_resumen_mes
from puntualidad_reporte import generar_informe_puntualidad_pdf
from puntualidad_service import obtener_estado_anual


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARPETA_ARCHIVOS = os.path.join(BASE_DIR, "archivos")


def _estado_icono(estado):
    return {
        "VERDE": "verde",
        "AMARILLO": "amarillo",
        "NARANJA": "naranja",
        "ROJO": "rojo",
        "ADVERTENCIA_ANUAL": "amarillo",
        "NORMAL": "normal",
    }.get(str(estado or "").upper(), "normal")


def _mes_actual():
    import datetime
    hoy = datetime.date.today()
    return hoy.year, hoy.month


class PuntualidadApp:
    def __init__(self, root, base_dir=None):
        self.root = root
        self.base_dir = base_dir or BASE_DIR
        self.ruta_archivo = None
        inicializar_base_puntualidad(self.base_dir)

        root.title("Control de Puntualidad")
        root.geometry("1080x650")
        root.minsize(960, 560)

        self.archivo_var = tk.StringVar(value="Sin archivo seleccionado")
        anio, mes = _mes_actual()
        self.anio_var = tk.StringVar(value=str(anio))
        self.mes_var = tk.IntVar(value=mes)
        self.mes_hasta_var = tk.IntVar(value=mes)
        self.depto_var = tk.StringVar(value="Todos")
        self.informe_var = tk.StringVar(value="Por periodo")
        self.desde_var = tk.StringVar(value="")
        self.hasta_var = tk.StringVar(value="")
        self.reemplazar_var = tk.BooleanVar(value=False)
        self.estado_var = tk.StringVar(value="Listo")
        self.estado_imgs = self._crear_estado_imgs()
        self._detalle_rows = {}

        self._crear_ui()
        self.cargar_resumen()

    def _crear_estado_imgs(self):
        colores = {
            "verde": ("#22c55e", "#166534"),
            "amarillo": ("#eab308", "#854d0e"),
            "naranja": ("#f97316", "#9a3412"),
            "rojo": ("#ef4444", "#991b1b"),
            "normal": ("#cbd5e1", "#64748b"),
        }
        imgs = {}
        for nombre, (relleno, borde) in colores.items():
            img = tk.PhotoImage(width=18, height=18)
            img.put("#ffffff", to=(0, 0, 18, 18))
            cx, cy, radio = 9, 9, 6
            for y in range(18):
                for x in range(18):
                    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                    if dist <= radio:
                        img.put(relleno, (x, y))
                    elif radio < dist <= radio + 1.3:
                        img.put(borde, (x, y))
            imgs[nombre] = img
        return imgs

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
        ttk.Label(filtro_box, text="Mes desde").grid(row=0, column=2, padx=(8, 2), pady=10)
        ttk.Combobox(
            filtro_box,
            textvariable=self.mes_var,
            values=list(range(1, 13)),
            width=5,
            state="readonly",
        ).grid(row=0, column=3, pady=10)
        ttk.Label(filtro_box, text="Hasta").grid(row=0, column=4, padx=(8, 2), pady=10)
        ttk.Combobox(
            filtro_box,
            textvariable=self.mes_hasta_var,
            values=list(range(1, 13)),
            width=5,
            state="readonly",
        ).grid(row=0, column=5, pady=10)
        ttk.Label(filtro_box, text="Depto").grid(row=0, column=6, padx=(8, 2), pady=10)
        ttk.Combobox(
            filtro_box,
            textvariable=self.depto_var,
            values=["Todos", "redes", "administracion"],
            width=16,
            state="readonly",
        ).grid(row=0, column=7, pady=10)
        ttk.Label(filtro_box, text="Informe").grid(row=0, column=8, padx=(8, 2), pady=10)
        ttk.Combobox(
            filtro_box,
            textvariable=self.informe_var,
            values=["Por periodo", "Anual"],
            width=10,
            state="readonly",
        ).grid(row=0, column=9, pady=10)
        ttk.Button(filtro_box, text="Cargar tardanzas", command=self.cargar_resumen).grid(
            row=0, column=10, padx=8, pady=10
        )
        ttk.Button(filtro_box, text="Imprimir / PDF", command=self.imprimir_informe).grid(
            row=0, column=11, padx=(0, 8), pady=10
        )
        filtro_box.columnconfigure(12, weight=1)

        paned = ttk.PanedWindow(tab_consultar, orient="vertical")
        paned.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        resumen_frame = ttk.Frame(paned)
        detalle_frame = ttk.Frame(paned)
        paned.add(resumen_frame, weight=3)
        paned.add(detalle_frame, weight=2)

        self.tree_resumen = self._crear_tree(
            resumen_frame,
            ("departamento", "legajo", "nombre", "dias", "tardanzas", "minutos"),
            {
                "departamento": ("Departamento", 130),
                "legajo": ("Legajo", 80),
                "nombre": ("Nombre", 280),
                "dias": ("Dias eval.", 90),
                "tardanzas": ("Tardanzas", 90),
                "minutos": ("Minutos", 80),
            },
            tree_col=("Estado", 70),
        )
        self.tree_resumen.bind("<<TreeviewSelect>>", lambda _e: self.cargar_detalle())

        self.tree_detalle = self._crear_tree(
            detalle_frame,
            ("fecha", "programada", "entrada", "minutos", "estado", "justificada", "observacion"),
            {
                "fecha": ("Fecha", 110),
                "programada": ("Prog.", 80),
                "entrada": ("Entrada", 80),
                "minutos": ("Min.", 70),
                "estado": ("Estado", 110),
                "justificada": ("Justificada", 220),
                "observacion": ("Observacion", 300),
            },
        )
        self.tree_detalle.tag_configure("justificada", foreground="#166534")
        self.tree_detalle.bind("<Double-1>", self._abrir_dialogo_justificar)

        ttk.Label(self.root, textvariable=self.estado_var, anchor="w").pack(
            fill="x", padx=12, pady=(0, 8)
        )

    def _crear_tree(self, parent, columnas, meta, tree_col=None):
        show = "tree headings" if tree_col else "headings"
        tree = ttk.Treeview(parent, columns=columnas, show=show)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        if tree_col:
            titulo, ancho = tree_col
            tree.heading("#0", text=titulo)
            tree.column("#0", width=ancho, minwidth=ancho, stretch=False, anchor="center")
        for col in columnas:
            titulo, ancho = meta[col]
            tree.heading(col, text=titulo)
            tree.column(col, width=ancho, anchor="center")
        if "nombre" in columnas:
            tree.column("nombre", anchor="w")
        if "observacion" in columnas:
            tree.column("observacion", anchor="w")
        if "justificada" in columnas:
            tree.column("justificada", anchor="w")
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return tree

    def _filtros(self):
        anio = int(self.anio_var.get().strip())
        mes = int(self.mes_var.get())
        depto = self.depto_var.get()
        return anio, mes, None if depto == "Todos" else depto

    def _rango_meses(self):
        desde = int(self.mes_var.get())
        hasta = int(self.mes_hasta_var.get())
        if desde > hasta:
            raise ValueError("El mes desde no puede ser posterior al mes hasta.")
        return desde, hasta

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
                self.base_dir,
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
            modo = self.informe_var.get()
            anual = modo == "Anual"
            mes, mes_hasta = self._rango_meses()
            rango = not anual and mes != mes_hasta
            if anual:
                rows = consultar_acumulado_anual(self.base_dir, anio, departamento=depto)
            elif rango:
                mes, mes_hasta = self._rango_meses()
                rows = consultar_resumen_rango(self.base_dir, anio, mes, mes_hasta, departamento=depto)
            else:
                rows = consultar_resumen_mes(self.base_dir, anio, mes, departamento=depto)
            rows = [
                r for r in rows
                if int(r["cantidad_tardanzas"] or 0) > 0
                or int(r.get("cantidad_justificadas") or 0) > 0
            ]
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self.root)
            return

        self._limpiar(self.tree_resumen)
        self._limpiar(self.tree_detalle)
        for r in rows:
            estado = (
                obtener_estado_anual(r["cantidad_tardanzas"])
                if anual or rango else r["estado_mensual"]
            )
            self.tree_resumen.insert("", "end", values=(
                r["departamento"],
                r["legajo"],
                r["nombre"],
                r["dias_evaluados"],
                r["cantidad_tardanzas"],
                r["minutos_tarde"],
            ), image=self.estado_imgs[_estado_icono(estado)])
        if anual:
            periodo = f"anio {anio}"
        elif rango:
            periodo = f"meses {mes:02d} a {mes_hasta:02d}/{anio}"
        else:
            periodo = f"{mes:02d}/{anio}"
        self.estado_var.set(f"Tardanzas de {periodo}: {len(rows)} empleados")

    def cargar_detalle(self):
        sel = self.tree_resumen.selection()
        if not sel:
            return
        vals = self.tree_resumen.item(sel[0], "values")
        legajo = vals[1]
        try:
            anio, mes, depto = self._filtros()
            modo = self.informe_var.get()
            anual = modo == "Anual"
            mes, hasta_seleccionado = self._rango_meses()
            rango = not anual and mes != hasta_seleccionado
            mes_desde = mes_hasta = None
            if rango:
                mes_desde, mes_hasta = mes, hasta_seleccionado
            rows = consultar_tardanzas(
                self.base_dir, anio,
                mes=mes if not anual and not rango else None,
                departamento=depto, legajo=legajo,
                mes_desde=mes_desde, mes_hasta=mes_hasta,
            )
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self.root)
            return

        self._limpiar(self.tree_detalle)
        self._detalle_rows = {}
        for r in rows:
            self._detalle_rows[str(r["id"])] = r
            justificada = bool(r.get("justificada"))
            texto_justif = ""
            if justificada:
                motivo = (r.get("motivo_justificacion") or "").strip()
                texto_justif = f"Si - {motivo}" if motivo else "Si"
            self.tree_detalle.insert(
                "", "end", iid=str(r["id"]),
                values=(
                    r["fecha"],
                    r["hora_programada"] or "",
                    r["hora_entrada"] or "",
                    r["minutos_tarde"],
                    r["estado_jornada"],
                    texto_justif,
                    r["observacion"] or "",
                ),
                tags=("justificada",) if justificada else (),
            )
        self.estado_var.set(f"Detalle cargado: legajo {legajo}, {len(rows)} llegadas tarde")

    def _abrir_dialogo_justificar(self, _event=None):
        sel = self.tree_detalle.selection()
        if not sel:
            return
        iid = sel[0]
        r = self._detalle_rows.get(iid)
        if not r:
            return

        win = tk.Toplevel(self.root)
        win.title(f"Justificar tardanza - {r['nombre']} ({r['fecha']})")
        win.transient(self.root)
        win.resizable(False, False)

        justificada_var = tk.BooleanVar(value=bool(r.get("justificada")))
        motivo_var = tk.StringVar(value=r.get("motivo_justificacion") or "")

        ttk.Label(win, text=f"{r['nombre']} - Legajo {r['legajo']} - {r['fecha']}").grid(
            row=0, column=0, columnspan=2, padx=10, pady=(10, 4), sticky="w")
        ttk.Checkbutton(win, text="Marcar como justificada", variable=justificada_var).grid(
            row=1, column=0, columnspan=2, padx=10, pady=4, sticky="w")
        ttk.Label(win, text="Motivo").grid(row=2, column=0, padx=10, pady=4, sticky="w")
        ttk.Entry(win, textvariable=motivo_var, width=48).grid(
            row=2, column=1, padx=(0, 10), pady=4)

        def _guardar():
            legajo = r["legajo"]
            try:
                if justificada_var.get():
                    motivo = motivo_var.get().strip()
                    if not motivo:
                        messagebox.showwarning(
                            "Falta motivo",
                            "Ingresa un motivo para justificar la tardanza.",
                            parent=win,
                        )
                        return
                    info = justificar_jornada(self.base_dir, int(iid), motivo)
                else:
                    info = desjustificar_jornada(self.base_dir, int(iid))
                if info:
                    recalcular_resumen_mes(self.base_dir, info["anio"], info["mes"])
            except Exception as exc:
                messagebox.showerror("Error", str(exc), parent=win)
                return
            win.destroy()
            self.cargar_resumen()
            self._reseleccionar_legajo(legajo)

        btns = ttk.Frame(win)
        btns.grid(row=3, column=0, columnspan=2, pady=(6, 10))
        ttk.Button(btns, text="Guardar", command=_guardar).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancelar", command=win.destroy).pack(side="left", padx=6)
        win.grab_set()

    def _reseleccionar_legajo(self, legajo):
        for item in self.tree_resumen.get_children():
            vals = self.tree_resumen.item(item, "values")
            if vals[1] == legajo:
                self.tree_resumen.selection_set(item)
                self.tree_resumen.see(item)
                return
        self._limpiar(self.tree_detalle)

    def imprimir_informe(self):
        try:
            anio, mes, depto = self._filtros()
            modo = self.informe_var.get()
            anual = modo == "Anual"
            mes, mes_hasta = self._rango_meses()
            rango = not anual and mes != mes_hasta
            if anual:
                resumenes = consultar_acumulado_anual(self.base_dir, anio, departamento=depto)
            elif rango:
                resumenes = consultar_resumen_rango(self.base_dir, anio, mes, mes_hasta, departamento=depto)
            else:
                resumenes = consultar_resumen_mes(self.base_dir, anio, mes, departamento=depto)
            resumenes = [
                r for r in resumenes
                if int(r["cantidad_tardanzas"] or 0) > 0
                or int(r.get("cantidad_justificadas") or 0) > 0
            ]
            tardanzas = consultar_tardanzas(
                self.base_dir, anio,
                mes=mes if not anual and not rango else None,
                departamento=depto,
                mes_desde=mes if rango else None,
                mes_hasta=mes_hasta if rango else None,
            )
            if not tardanzas:
                messagebox.showinfo("Sin tardanzas", "No hay llegadas tarde para imprimir.", parent=self.root)
                return
            if anual:
                sufijo = f"{anio}"
            elif rango:
                sufijo = f"{anio}_{mes:02d}_a_{mes_hasta:02d}"
            else:
                sufijo = f"{anio}_{mes:02d}"
            ruta = filedialog.asksaveasfilename(
                parent=self.root,
                title="Guardar informe de puntualidad",
                initialdir=os.path.join(self.base_dir, "reportes"),
                initialfile=f"informe_tardanzas_{sufijo}.pdf",
                defaultextension=".pdf",
                filetypes=[("Documento PDF", "*.pdf")],
            )
            if not ruta:
                return
            generar_informe_puntualidad_pdf(
                self.base_dir, ruta, anio, None if anual else mes, resumenes, tardanzas,
                mes_hasta=mes_hasta if rango else None,
            )
            self.estado_var.set(f"Informe generado: {ruta}")
            if os.name == "nt":
                os.startfile(ruta)
            else:
                messagebox.showinfo("Informe generado", ruta, parent=self.root)
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self.root)


def abrir_control_puntualidad(parent=None, base_dir=None):
    win = tk.Toplevel(parent) if parent else tk.Tk()
    if parent:
        win.transient(parent)
    PuntualidadApp(win, base_dir=base_dir)
    return win


def main():
    root = tk.Tk()
    PuntualidadApp(root, base_dir=BASE_DIR)
    root.mainloop()


if __name__ == "__main__":
    main()
