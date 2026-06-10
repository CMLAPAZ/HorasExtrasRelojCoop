# -*- coding: utf-8 -*-
"""
resumen_estadistico.py
Resumen estadístico del período
NO modifica lógica existente
"""

from datetime import timedelta, datetime
from collections import defaultdict


# ---------------------------------------------------------
# Helpers seguros
# ---------------------------------------------------------
def _parse_fecha(fecha_str):
    if not fecha_str:
        return None
    s = str(fecha_str).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None


def _min_from_any(x):
    if x is None:
        return 0
    if isinstance(x, timedelta):
        return int(x.total_seconds() // 60)
    if isinstance(x, (int, float)):
        return int(x)

    s = str(x).strip()
    if not s or s.lower() in ("nan", "none"):
        return 0

    # Pandas a veces stringify-a como "0 days 01:30:00"
    if "days" in s:
        s = s.split()[-1]

    try:
        parts = s.split(":")
        if len(parts) >= 2:
            return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return 0

    return 0


def _hhmm_from_min(mins):
    mins = int(mins or 0)
    return f"{mins // 60:02d}:{mins % 60:02d}"


# ---------------------------------------------------------
# Iterador ROBUSTO (evita list.get y soporta mezclas/anidados)
# ---------------------------------------------------------
def _iter_registros(data):
    if not data:
        return

    def walk(items, leg_ctx="", nom_ctx=""):
        if not items:
            return

        # Si viene un dict suelto, lo tratamos como una lista de 1
        if isinstance(items, dict):
            items = [items]

        for item in items:
            # Dict: puede ser "empleado con registros" o "registro plano"
            if isinstance(item, dict):
                # Caso: por empleado {legajo, nombre, registros:[...]}
                if "registros" in item and isinstance(item.get("registros"), list):
                    leg = str(item.get("legajo", leg_ctx) or "").strip()
                    nom = str(item.get("nombre", nom_ctx) or "").strip()
                    yield from walk(item.get("registros", []), leg, nom)
                    continue

                # Caso: registro plano (una fila)
                leg = leg_ctx or str(item.get("Legajo", item.get("legajo", "")) or "").strip()
                nom = nom_ctx or str(item.get("Nombre", item.get("nombre", "")) or "").strip()
                yield leg, nom, item
                continue

            # Lista: puede ser anidada o mezcla rara -> entrar recursivo
            if isinstance(item, list):
                yield from walk(item, leg_ctx, nom_ctx)
                continue

            # Otros tipos (None, str, int, etc.): se ignoran

    # Si viene un dict envolviendo datos (por si en algún lado cambiaste el formato)
    if isinstance(data, dict):
        for k in ("resultados", "data", "rows"):
            if k in data:
                data = data[k]
                break

    yield from walk(data)


# ---------------------------------------------------------
# FUNCIÓN PRINCIPAL
# ---------------------------------------------------------
def generar_resumen(resultados_aplanados):
    por_emp = {}

    por_mes = defaultdict(lambda: {
        "min_50": 0,
        "min_100": 0,
        "min_extra_total": 0,
        "francos": 0,
        "tardes": 0,
        "salidas_anticipadas": 0
    })

    gen = {
        "min_50": 0,
        "min_100": 0,
        "francos": 0,
        "comidas": 0,
        "tardes": 0,
        "salidas_anticipadas": 0
    }

    for leg, nom, r in _iter_registros(resultados_aplanados):
        if not isinstance(r, dict):
            continue

        m50 = _min_from_any(r.get("50%", "0"))
        m100 = _min_from_any(r.get("100%", "0"))

        franco = int(r.get("FRANCO", 0) or 0)
        comida = int(r.get("COMIDA", 0) or 0)
        tarde = int(r.get("Tarde", 0) or 0)

        obs = str(r.get("Observaciones", "") or "")
        sa = 1 if "SA" in obs else 0

        f = _parse_fecha(r.get("Fecha"))
        ym = f"{f.year}-{f.month:02d}" if f else None

        if leg not in por_emp:
            por_emp[leg] = {
                "legajo": leg,
                "nombre": nom,
                "min_50": 0,
                "min_100": 0,
                "min_extra_total": 0,
                "francos": 0,
                "comidas": 0,
                "tardes": 0,
                "salidas_anticipadas": 0
            }

        e = por_emp[leg]
        e["min_50"] += m50
        e["min_100"] += m100
        e["min_extra_total"] += (m50 + m100)
        e["francos"] += franco
        e["comidas"] += comida
        e["tardes"] += tarde
        e["salidas_anticipadas"] += sa

        gen["min_50"] += m50
        gen["min_100"] += m100
        gen["francos"] += franco
        gen["comidas"] += comida
        gen["tardes"] += tarde
        gen["salidas_anticipadas"] += sa

        if ym:
            pm = por_mes[ym]
            pm["min_50"] += m50
            pm["min_100"] += m100
            pm["min_extra_total"] += (m50 + m100)
            pm["francos"] += franco
            pm["tardes"] += tarde
            pm["salidas_anticipadas"] += sa

    # Rankings TOP 3
    def top3(metric, hhmm=False):
        lst = [(v[metric], v) for v in por_emp.values() if v.get(metric, 0) > 0]
        lst.sort(reverse=True, key=lambda x: x[0])
        out = []
        for v, d in lst[:3]:
            item = {"legajo": d["legajo"], "nombre": d["nombre"]}
            item["valor"] = _hhmm_from_min(v) if hhmm else v
            out.append(item)
        return out

    return {
        "generales": {
            **gen,
            "min_extra_total": gen["min_50"] + gen["min_100"],
            "hhmm_50": _hhmm_from_min(gen["min_50"]),
            "hhmm_100": _hhmm_from_min(gen["min_100"]),
            "hhmm_extra_total": _hhmm_from_min(gen["min_50"] + gen["min_100"]),
        },
        "por_empleado": por_emp,
        "por_mes": dict(por_mes),
        "rankings": {
            "mas_horas_extras": top3("min_extra_total", hhmm=True),
            "mas_francos": top3("francos"),
            "mas_tardes": top3("tardes"),
            "mas_salidas_anticipadas": top3("salidas_anticipadas"),
        }
    }
