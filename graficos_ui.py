# -*- coding: utf-8 -*-
"""
graficos_ui.py
Panel de gráficos para el resumen estadístico.
- Selector de tipo de gráfico
- Soporta por empleado y por mes
- Guardar PNG

Requiere: matplotlib
"""

import os
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


# ----------------------------
# Helpers de datos
# ----------------------------
def _hours(mins) -> float:
    try:
        return float(int(mins or 0)) / 60.0
    except Exception:
        return 0.0


def _empleados_rows(resumen):
    """Lista de (nombre, h50, h100, total). Solo con total>0, ordenado desc por total."""
    por_emp = resumen.get("por_empleado", {}) or {}
    filas = []
    if not isinstance(por_emp, dict):
        return filas

    for d in por_emp.values():
        if not isinstance(d, dict):
            continue
        h50 = _hours(d.get("min_50", 0))
        h100 = _hours(d.get("min_100", 0))
        total = h50 + h100
        if total <= 0:
            continue
        nombre = (d.get("nombre") or "—").strip()
        filas.append((nombre, h50, h100, total))

    filas.sort(key=lambda x: x[3], reverse=True)
    return filas


def _mes_rows(resumen):
    """Lista de (label, h50, h100, total) ordenada por YYYY-MM."""
    por_mes = resumen.get("por_mes", {}) or {}
    filas = []
    if not isinstance(por_mes, dict) or not por_mes:
        return filas

    keys = sorted([k for k in por_mes.keys() if isinstance(k, str)])
    for ym in keys:
        d = por_mes.get(ym)
        if not isinstance(d, dict):
            continue
        h50 = _hours(d.get("min_50", 0))
        h100 = _hours(d.get("min_100", 0))
        total = h50 + h100
        # Etiqueta MM/YYYY
        try:
            y, m = ym.split("-")
            label = f"{m}/{y}"
        except Exception:
            label = ym
        filas.append((label, h50, h100, total))
    return filas


# ----------------------------
# Render de gráficos
# ----------------------------
def _clear_ax(ax):
    ax.clear()
    ax.grid(False)


def _plot_empleados_apilado(ax, rows):
    # Barras apiladas 50 + 100 (todos)
    nombres = [r[0] for r in rows]
    h50s = [r[1] for r in rows]
    h100s = [r[2] for r in rows]
    x = list(range(len(nombres)))

    ax.bar(x, h50s, label="Horas 50%")
    ax.bar(x, h100s, bottom=h50s, label="Horas 100%")
    ax.set_title("Horas extras por empleado (barras apiladas)")
    ax.set_ylabel("Horas")
    ax.set_xlabel("Empleado")
    ax.set_xticks(x)
    ax.set_xticklabels(nombres, rotation=45, ha="right")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.35)


def _plot_empleados_agrupado(ax, rows):
    # Barras lado a lado 50 vs 100 (todos)
    nombres = [r[0] for r in rows]
    h50s = [r[1] for r in rows]
    h100s = [r[2] for r in rows]
    x = list(range(len(nombres)))

    w = 0.45
    ax.bar([i - w/2 for i in x], h50s, width=w, label="Horas 50%")
    ax.bar([i + w/2 for i in x], h100s, width=w, label="Horas 100%")
    ax.set_title("Horas extras por empleado (barras agrupadas)")
    ax.set_ylabel("Horas")
    ax.set_xlabel("Empleado")
    ax.set_xticks(x)
    ax.set_xticklabels(nombres, rotation=45, ha="right")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.35)


def _plot_empleados_total_top(ax, rows, n=15):
    # Top N por total (para cuando hay muchos empleados, es legible)
    rows = rows[:max(1, int(n))]
    nombres = [r[0] for r in rows]
    tot = [r[3] for r in rows]
    x = list(range(len(nombres)))

    ax.bar(x, tot, label="Total (50%+100%)")
    ax.set_title(f"Top {len(nombres)} por horas extras totales")
    ax.set_ylabel("Horas")
    ax.set_xlabel("Empleado")
    ax.set_xticks(x)
    ax.set_xticklabels(nombres, rotation=45, ha="right")
    ax.grid(axis="y", linestyle="--", alpha=0.35)


def _plot_scatter_50_100(ax, rows):
    # Dispersión: 50 vs 100 por empleado
    h50s = [r[1] for r in rows]
    h100s = [r[2] for r in rows]
    ax.scatter(h50s, h100s)
    ax.set_title("Dispersión por empleado: Horas 50% vs Horas 100%")
    ax.set_xlabel("Horas 50%")
    ax.set_ylabel("Horas 100%")
    ax.grid(True, linestyle="--", alpha=0.35)


def _plot_mes_apilado(ax, rows):
    labels = [r[0] for r in rows]
    h50s = [r[1] for r in rows]
    h100s = [r[2] for r in rows]
    x = list(range(len(labels)))

    ax.bar(x, h50s, label="Horas 50%")
    ax.bar(x, h100s, bottom=h50s, label="Horas 100%")
    ax.set_title("Horas extras por mes (barras apiladas)")
    ax.set_ylabel("Horas")
    ax.set_xlabel("Mes")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.35)


def _plot_mes_linea_total(ax, rows):
    labels = [r[0] for r in rows]
    tot = [r[3] for r in rows]
    x = list(range(len(labels)))

    ax.plot(x, tot, marker="o")
    ax.set_title("Evolución mensual: horas extras totales")
    ax.set_ylabel("Horas")
    ax.set_xlabel("Mes")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.grid(True, linestyle="--", alpha=0.35)


def _plot_mes_linea_doble(ax, rows):
    labels = [r[0] for r in rows]
    h50s = [r[1] for r in rows]
    h100s = [r[2] for r in rows]
    x = list(range(len(labels)))

    ax.plot(x, h50s, marker="o", label="50%")
    ax.plot(x, h100s, marker="o", label="100%")
    ax.set_title("Evolución mensual: 50% y 100% por separado")
    ax.set_ylabel("Horas")
    ax.set_xlabel("Mes")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    ax.grid(True, linestyle="--", alpha=0.35)


def _plot_hist_total_empleados(ax, rows):
    tot = [r[3] for r in rows]
    ax.hist(tot, bins=12)
    ax.set_title("Distribución: horas extras totales por empleado")
    ax.set_xlabel("Horas (total 50%+100%)")
    ax.set_ylabel("Cantidad de empleados")
    ax.grid(True, linestyle="--", alpha=0.35)


# ----------------------------
# UI principal
# ----------------------------
def mostrar_panel_graficos(resumen, carpeta_reportes=None, parent=None):
    _F = "Segoe UI"
    _BG = "#f2faff"
    _TITLE = "#1a435b"

    win = tk.Toplevel(parent) if parent else tk.Toplevel()
    win.title("Panel de gráficos — Resumen estadístico")
    win.geometry("1280x800")
    win.configure(bg=_BG)

    # Layout: barra superior (selector + botones) y área de gráfico
    topbar = tk.Frame(win, bg=_BG)
    topbar.pack(fill="x", padx=14, pady=10)

    tk.Label(topbar, text="Tipo de gráfico:", font=(_F, 10, "bold"), bg=_BG, fg=_TITLE).pack(side="left")

    opciones = [
        "Empleados: Barras apiladas 50/100 (todos)",
        "Empleados: Barras agrupadas 50 vs 100 (todos)",
        "Empleados: Top 15 total (legible)",
        "Empleados: Dispersión 50 vs 100",
        "Empleados: Histograma totales",
        "Meses: Barras apiladas 50/100",
        "Meses: Línea total",
        "Meses: Líneas 50 y 100",
    ]

    cbo = ttk.Combobox(topbar, values=opciones, state="readonly", width=46)
    cbo.current(0)
    cbo.pack(side="left", padx=10)

    fig = Figure(figsize=(12, 6.5), dpi=100)
    ax = fig.add_subplot(111)

    canvas = FigureCanvasTkAgg(fig, master=win)
    canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # Datos base
    rows_emp = _empleados_rows(resumen)
    rows_mes = _mes_rows(resumen)

    def _render():
        _clear_ax(ax)

        sel = cbo.get()
        if not rows_emp and sel.startswith("Empleados"):
            ax.text(0.5, 0.5, "No hay horas extras por empleado para graficar",
                    ha="center", va="center", fontsize=12)
            ax.set_axis_off()
            canvas.draw()
            return

        if not rows_mes and sel.startswith("Meses"):
            ax.text(0.5, 0.5, "No hay datos por mes (por_mes) para graficar",
                    ha="center", va="center", fontsize=12)
            ax.set_axis_off()
            canvas.draw()
            return

        if sel == "Empleados: Barras apiladas 50/100 (todos)":
            _plot_empleados_apilado(ax, rows_emp)
        elif sel == "Empleados: Barras agrupadas 50 vs 100 (todos)":
            _plot_empleados_agrupado(ax, rows_emp)
        elif sel == "Empleados: Top 15 total (legible)":
            _plot_empleados_total_top(ax, rows_emp, n=15)
        elif sel == "Empleados: Dispersión 50 vs 100":
            _plot_scatter_50_100(ax, rows_emp)
        elif sel == "Empleados: Histograma totales":
            _plot_hist_total_empleados(ax, rows_emp)
        elif sel == "Meses: Barras apiladas 50/100":
            _plot_mes_apilado(ax, rows_mes)
        elif sel == "Meses: Línea total":
            _plot_mes_linea_total(ax, rows_mes)
        elif sel == "Meses: Líneas 50 y 100":
            _plot_mes_linea_doble(ax, rows_mes)

        fig.tight_layout()
        canvas.draw()

    def _guardar_png():
        # sugerir carpeta_reportes si existe
        initdir = carpeta_reportes if (carpeta_reportes and os.path.isdir(carpeta_reportes)) else None
        sugerido = "grafico_" + _dt_stamp() + ".png"
        ruta = filedialog.asksaveasfilename(
            parent=win,
            defaultextension=".png",
            initialfile=sugerido,
            initialdir=initdir,
            filetypes=[("PNG", "*.png"), ("Todos", "*.*")]
        )
        if not ruta:
            return
        try:
            fig.savefig(ruta, dpi=150)
            messagebox.showinfo("OK", f"Guardado:\n{ruta}", parent=win)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar PNG:\n{e}", parent=win)

    def _dt_stamp():
        import datetime as _dt
        return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    tk.Button(topbar, text="Guardar PNG…", command=_guardar_png,
              font=(_F, 10, "bold"), bg="#afe9b7", width=14).pack(side="left", padx=8)
    tk.Button(topbar, text="Cerrar", command=win.destroy,
              font=(_F, 10), bg="#d9eaf7", width=10).pack(side="right")

    cbo.bind("<<ComboboxSelected>>", lambda e: _render())

    _render()
    if parent:
        win.transient(parent)
    win.focus_set()
