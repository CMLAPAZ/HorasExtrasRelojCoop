# -*- coding: utf-8 -*-
"""
Módulo: resumen_ui.py
Ventana previa para mostrar el resumen estadístico en pantalla,
con opción de guardar a TXT y CSV (Top 10).

No modifica cálculos. Solo presenta y guarda.
"""

from __future__ import annotations

import os
import csv
import datetime as _dt
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox
from typing import Any, Dict, List


def _now_stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _min_to_hhmm(minutos: int) -> str:
    minutos = max(0, int(minutos or 0))
    hh = minutos // 60
    mm = minutos % 60
    return f"{hh:02d}:{mm:02d}"


def _fmt_persona(item: Any) -> str:
    """
    Acepta:
    - dict {"legajo","nombre","valor"}
    - lista [dict, dict, dict] (Top 3) -> lo muestra completo
    """
    if not item:
        return "—"

    # TOP 3 (lista)
    if isinstance(item, list):
        out = []
        for i, it in enumerate(item[:3], start=1):
            if not isinstance(it, dict):
                continue
            leg = (it.get("legajo") or "").strip()
            nom = (it.get("nombre") or "").strip()
            val = it.get("valor", "—")
            if nom and leg:
                out.append(f"{i}) {nom} (Legajo {leg}) — {val}")
            elif nom:
                out.append(f"{i}) {nom} — {val}")
            else:
                out.append(f"{i}) — {val}")
        return "\n".join(out) if out else "—"

    # TOP 1 (dict)
    if isinstance(item, dict):
        leg = (item.get("legajo") or "").strip()
        nom = (item.get("nombre") or "").strip()
        val = item.get("valor", "—")
        if leg and nom:
            return f"{nom} (Legajo {leg}) — {val}"
        if nom:
            return f"{nom} — {val}"
        return f"— {val}"

    return "—"


    leg = (item.get("legajo") or "").strip()
    nom = (item.get("nombre") or "").strip()
    val = item.get("valor", "—")

    if leg and nom:
        return f"{nom} (Legajo {leg}) — {val}"
    if nom:
        return f"{nom} — {val}"
    return f"— {val}"


def _build_conclusiones(resumen: Dict[str, Any], periodo_texto: str) -> str:
    r = resumen.get("rankings", {}) or {}
    g = resumen.get("generales", {}) or {}

    mas_extras = _fmt_persona(r.get("mas_horas_extras"))
    mas_fr = _fmt_persona(r.get("mas_francos"))
    mas_tarde = _fmt_persona(r.get("mas_tardes"))
    mas_sa = _fmt_persona(r.get("mas_salidas_anticipadas"))

    # Mes con más extras (si hay por_mes)
    por_mes = resumen.get("por_mes", {}) or {}
    mes_max = "—"
    if isinstance(por_mes, dict) and por_mes:
        best = None
        for ym, d in por_mes.items():
            if not isinstance(d, dict):
                continue
            try:
                v = int(d.get("min_extra_total", 0) or 0)
            except Exception:
                v = 0
            if best is None or v > best[1]:
                best = (ym, v)
        if best:
            ym, v = best
            mes_max = f"{ym} — {_min_to_hhmm(v)}"

    tot50 = g.get("hhmm_50", "—")
    tot100 = g.get("hhmm_100", "—")
    totxt = g.get("hhmm_extra_total", "—")
    tot_fr = g.get("francos", 0)
    tot_com = g.get("comidas", 0)
    tot_tarde = g.get("tardes", 0)
    tot_sa = g.get("salidas_anticipadas", 0)

    lineas = [
        f"RESUMEN ESTADÍSTICO — {periodo_texto}",
        "",
        "CONCLUSIONES DEL PERÍODO",
        "• Top 3 — Más horas extras (50%+100%):",
        f"{mas_extras}","",
        "• Top 3 — Más francos:",
        f"{mas_fr}","",
        "• Top 3 — Más llegadas tarde:",
        f"{mas_tarde}","",
        "• Top 3 — Más salidas anticipadas:",
        f"{mas_sa}","",
        f"• Mes con mayor carga de extras: {mes_max}",
        "",
        "TOTALES DEL PERÍODO",
        f"• Total 50%: {tot50}",
        f"• Total 100%: {tot100}",
        f"• Total extras (50%+100%): {totxt}",
        f"• Total francos: {tot_fr}",
        f"• Total comidas: {tot_com}",
        f"• Total tardes: {tot_tarde}",
        f"• Total salidas anticipadas: {tot_sa}",
    ]
    return "\n".join(lineas)


def _top_n_por_extras(resumen: Dict[str, Any], n: int = 10) -> List[Dict[str, Any]]:
    """
    Devuelve lista de dicts para Top N por min_extra_total.
    """
    por_emp = resumen.get("por_empleado", {}) or {}
    items: List[Dict[str, Any]] = []

    if not isinstance(por_emp, dict):
        return items

    for d in por_emp.values():
        if not isinstance(d, dict):
            continue
        try:
            min_total = int(d.get("min_extra_total", 0) or 0)
        except Exception:
            min_total = 0

        items.append({
            "legajo": (d.get("legajo") or "").strip(),
            "nombre": (d.get("nombre") or "").strip(),
            "min_extra_total": min_total,
            "min_50": int(d.get("min_50", 0) or 0),
            "min_100": int(d.get("min_100", 0) or 0),
            "francos": int(d.get("francos", 0) or 0),
            "tardes": int(d.get("tardes", 0) or 0),
            "sa": int(d.get("salidas_anticipadas", 0) or 0),
        })

    items.sort(key=lambda x: (x["min_extra_total"], x["nombre"]), reverse=True)
    return items[:max(1, int(n))]


def mostrar_resumen(resumen: Dict[str, Any], carpeta_reportes: str, periodo_texto: str, parent=None):
    """
    Abre una ventana con:
    - conclusiones en un Text (solo lectura)
    - tabla Top 10 por horas extras
    - botones: Guardar TXT / Guardar CSV / Cerrar
    """
    # Creamos ventana primero, y recién luego layout (para evitar "left" sin asignar)
    _F    = "Segoe UI"
    _BG   = "#f2faff"
    _TITLE= "#1a435b"

    win = tk.Toplevel(parent) if parent else tk.Toplevel()
    win.title("Resumen estadístico del período")
    win.geometry("1000x740")
    win.configure(bg=_BG)

    # Header
    tk.Label(
        win,
        text="Resumen estadístico del período",
        font=(_F, 15, "bold"), bg=_BG, fg=_TITLE
    ).pack(pady=(14, 4))

    tk.Label(
        win,
        text=periodo_texto,
        font=(_F, 11), bg=_BG, fg=_TITLE
    ).pack(pady=(0, 10))

    # Frame principal (2 columnas)
    main = tk.Frame(win, bg="#f2faff")
    main.pack(fill="both", expand=True, padx=14, pady=10)

    left = tk.Frame(main, bg=_BG)
    left.pack(side="left", fill="both", expand=True, padx=(0, 10))

    right = tk.Frame(main, bg=_BG)
    right.pack(side="right", fill="both", expand=True)

    # Conclusiones (Text read-only)
    tk.Label(left, text="Conclusiones", font=(_F, 12, "bold"), bg=_BG, fg=_TITLE).pack(anchor="w")

    txt = tk.Text(left, height=22, wrap="word", font=("Consolas", 10))
    txt.pack(fill="both", expand=True, pady=(6, 0))

    conclusiones = _build_conclusiones(resumen, periodo_texto)
    txt.insert("1.0", conclusiones)
    txt.configure(state="disabled")

    # Tabla Top 10
    tk.Label(right, text="Top 10 — Horas extras (50% + 100%)", font=(_F, 12, "bold"), bg=_BG, fg=_TITLE).pack(anchor="w")

    cols = ("legajo", "nombre", "extras", "50", "100", "francos", "tardes", "SA")
    tree = ttk.Treeview(right, columns=cols, show="headings", height=18)
    tree.pack(fill="both", expand=True, pady=(6, 0))

    tree.heading("legajo", text="Legajo")
    tree.heading("nombre", text="Nombre")
    tree.heading("extras", text="Extras")
    tree.heading("50", text="50%")
    tree.heading("100", text="100%")
    tree.heading("francos", text="Francos")
    tree.heading("tardes", text="Tardes")
    tree.heading("SA", text="SA")

    tree.column("legajo", width=80, anchor="center")
    tree.column("nombre", width=220, anchor="w")
    tree.column("extras", width=90, anchor="center")
    tree.column("50", width=80, anchor="center")
    tree.column("100", width=80, anchor="center")
    tree.column("francos", width=70, anchor="center")
    tree.column("tardes", width=70, anchor="center")
    tree.column("SA", width=60, anchor="center")

    top = _top_n_por_extras(resumen, 10)
    for it in top:
        tree.insert("", "end", values=(
            it["legajo"],
            it["nombre"],
            _min_to_hhmm(it["min_extra_total"]),
            _min_to_hhmm(it["min_50"]),
            _min_to_hhmm(it["min_100"]),
            it["francos"],
            it["tardes"],
            it["sa"]
        ))

    # Botonera
    botones = tk.Frame(win, bg="#f2faff")
    botones.pack(fill="x", padx=14, pady=14)

    def _guardar_txt():
        try:
            os.makedirs(carpeta_reportes, exist_ok=True)
        except Exception:
            pass

        sugerido = os.path.join(carpeta_reportes, f"resumen_estadistico_{_now_stamp()}.txt")
        ruta = filedialog.asksaveasfilename(
            parent=win,
            defaultextension=".txt",
            initialfile=os.path.basename(sugerido),
            initialdir=carpeta_reportes if os.path.isdir(carpeta_reportes) else None,
            filetypes=[("Texto", "*.txt"), ("Todos", "*.*")]
        )
        if not ruta:
            return
        try:
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(conclusiones + "\n\n")
                f.write("TOP 10 — Horas extras (50% + 100%)\n")
                for it in top:
                    f.write(
                        f"- {it['nombre']} (Legajo {it['legajo']}): "
                        f"Extras {_min_to_hhmm(it['min_extra_total'])} | "
                        f"50 {_min_to_hhmm(it['min_50'])} | "
                        f"100 {_min_to_hhmm(it['min_100'])} | "
                        f"Francos {it['francos']} | Tardes {it['tardes']} | SA {it['sa']}\n"
                    )
            messagebox.showinfo("OK", f"Guardado:\n{ruta}", parent=win)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar TXT:\n{e}", parent=win)

    def _guardar_csv_top10():
        try:
            os.makedirs(carpeta_reportes, exist_ok=True)
        except Exception:
            pass

        sugerido = os.path.join(carpeta_reportes, f"top10_extras_{_now_stamp()}.csv")
        ruta = filedialog.asksaveasfilename(
            parent=win,
            defaultextension=".csv",
            initialfile=os.path.basename(sugerido),
            initialdir=carpeta_reportes if os.path.isdir(carpeta_reportes) else None,
            filetypes=[("CSV", "*.csv"), ("Todos", "*.*")]
        )
        if not ruta:
            return
        try:
            with open(ruta, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["Legajo", "Nombre", "Extras(HH:MM)", "50(HH:MM)", "100(HH:MM)", "Francos", "Tardes", "SA"])
                for it in top:
                    w.writerow([
                        it["legajo"],
                        it["nombre"],
                        _min_to_hhmm(it["min_extra_total"]),
                        _min_to_hhmm(it["min_50"]),
                        _min_to_hhmm(it["min_100"]),
                        it["francos"],
                        it["tardes"],
                        it["sa"],
                    ])
            messagebox.showinfo("OK", f"Guardado:\n{ruta}", parent=win)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar CSV:\n{e}", parent=win)

    tk.Button(botones, text="Guardar TXT…",      command=_guardar_txt,      font=(_F, 10, "bold"), bg="#71c7ec", width=16).pack(side="left", padx=(0, 10))
    tk.Button(botones, text="Guardar CSV Top10…", command=_guardar_csv_top10, font=(_F, 10, "bold"), bg="#afe9b7", width=18).pack(side="left")
    tk.Button(botones, text="Cerrar",             command=win.destroy,        font=(_F, 10, "bold"), bg="#f4978e", width=12).pack(side="right")

    if parent:
        win.transient(parent)
    win.grab_set()
    win.focus_set()
    win.wait_window()

