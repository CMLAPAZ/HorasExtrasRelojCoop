# -*- coding: utf-8 -*-
from flask import Flask, request, render_template, jsonify
import pandas as pd
import secrets
import json
from datetime import datetime, timedelta
from pathlib import Path
import socket

from procesador import procesar_fichadas, aplanar_registros_por_tramo

app = Flask(__name__)

SESION_FILE = Path("sesion.json")


# ─────────────────────────────────────────────
# Persistencia de sesión en disco
# ─────────────────────────────────────────────
def _cargar_sesion():
    if SESION_FILE.exists():
        try:
            return json.loads(SESION_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _guardar_sesion(sesion):
    SESION_FILE.write_text(json.dumps(sesion, ensure_ascii=False, indent=2), encoding="utf-8")

_sesion = _cargar_sesion()


# ─────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────
def _parse_td(s):
    if not s or s == "00:00:00":
        return timedelta(0)
    h, m, sec = map(int, s.split(":"))
    return timedelta(hours=h, minutes=m, seconds=sec)


def _fmt_hm(td):
    total = int(td.total_seconds())
    if total <= 0:
        return "0h"
    h = total // 3600
    m = (total % 3600) // 60
    return f"{h}h {m:02d}m" if m else f"{h}h"


def _preparar_dias(registros):
    """Devuelve una lista de días con tramos, totales, y campo para descripción."""
    dias_dict = {}
    dias_order = []

    for r in registros:
        fecha = r["Fecha"]
        if fecha not in dias_dict:
            dias_order.append(fecha)
            tiene_ot = (
                r["50%"]  != "00:00:00" or
                r["100%"] != "00:00:00" or
                int(r.get("FRANCO", 0)) > 0 or
                int(r.get("COMIDA", 0)) > 0
            )
            dias_dict[fecha] = {
                "fecha":      fecha,
                "fecha_fmt":  fecha[5:],   # MM-DD
                "tramos":     [],
                "normales":   r["Normales"],
                "ot50":       r["50%"],
                "ot100":      r["100%"],
                "comida":     int(r.get("COMIDA", 0)),
                "franco":     int(r.get("FRANCO", 0)),
                "tarde":      int(r.get("Tarde",  0)),
                "tiene_ot":   tiene_ot,
                "descripcion": "",
            }
        entrada = r.get("Entrada", "")
        salida  = r.get("Salida",  "")
        if entrada:
            dias_dict[fecha]["tramos"].append({
                "entrada": entrada[:5],
                "salida":  salida[:5] if salida else "—",
            })

    return [dias_dict[f] for f in dias_order]


def _leer_archivo(file_storage):
    nombre = (file_storage.filename or "").lower()
    if nombre.endswith(".xlsx"):
        return pd.read_excel(file_storage, engine="openpyxl")
    if nombre.endswith(".xls"):
        return pd.read_excel(file_storage, engine="xlrd")
    for enc in ("utf-8", "latin-1", "cp1252"):
        for sep in (";", ","):
            try:
                file_storage.seek(0)
                return pd.read_csv(file_storage, sep=sep, encoding=enc)
            except Exception:
                continue
    raise ValueError("No se pudo leer el archivo — usá .xls, .xlsx o .csv.")


def _normalizar_columnas(df):
    aliases = {
        "Nro. de usuario":  "Legajo",
        "Fecha/Hora":       "FechaHora",
        "Tipo de registro": "Tipo",
        "Fecha_Hora":       "FechaHora",
        "Fecha/hora":       "FechaHora",
        "fecha_hora":       "FechaHora",
        "Depto":            "Departamento",
        "depto":            "Departamento",
        "departamento":     "Departamento",
        "nro_usuario":      "Legajo",
        "legajo":           "Legajo",
        "nombre":           "Nombre",
        "tipo":             "Tipo",
    }
    return df.rename(columns={k: v for k, v in aliases.items() if k in df.columns})


# ─────────────────────────────────────────────
# Rutas
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("supervisor.html")


@app.route("/procesar", methods=["POST"])
def procesar():
    if "csv" not in request.files:
        return jsonify({"error": "No se recibió archivo"}), 400

    try:
        df = _leer_archivo(request.files["csv"])
        df = _normalizar_columnas(df)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    try:
        resultados = procesar_fichadas(df)
        empleados  = aplanar_registros_por_tramo(resultados)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    base_url = request.host_url.rstrip("/")

    links = []
    for emp in empleados:
        token = secrets.token_urlsafe(10)

        ot50 = ot100 = timedelta(0)
        comidas = francos = tardanzas = 0
        vistos = set()
        for r in emp["registros"]:
            f = r["Fecha"]
            if f in vistos:
                continue
            vistos.add(f)
            ot50      += _parse_td(r["50%"])
            ot100     += _parse_td(r["100%"])
            comidas   += int(r.get("COMIDA", 0))
            francos   += int(r.get("FRANCO", 0))
            tardanzas += int(r.get("Tarde", 0))

        _sesion[token] = {
            "legajo":       emp["legajo"],
            "nombre":       emp["nombre"],
            "departamento": emp["departamento"],
            "dias":         _preparar_dias(emp["registros"]),
            "totales": {
                "ot50":      _fmt_hm(ot50),
                "ot100":     _fmt_hm(ot100),
                "comidas":   comidas,
                "francos":   francos,
                "tardanzas": tardanzas,
            },
            "confirmado":    False,
            "confirmado_en": None,
        }

    _guardar_sesion(_sesion)

    for emp in empleados:
        # encontrar el token recién creado para este empleado
        token = next(
            t for t, d in _sesion.items()
            if d["legajo"] == emp["legajo"] and d["nombre"] == emp["nombre"]
            and not d["confirmado"]
        )
        links.append({
            "legajo": emp["legajo"],
            "nombre": emp["nombre"],
            "url":    f"{base_url}/e/{token}",
        })

    return jsonify({"empleados": links})


@app.route("/estado")
def estado():
    resultado = []
    for data in _sesion.values():
        resultado.append({
            "legajo":     data["legajo"],
            "nombre":     data["nombre"],
            "confirmado": data["confirmado"],
            "dias": [
                {
                    "fecha":       d["fecha"],
                    "ot50":        d["ot50"],
                    "ot100":       d["ot100"],
                    "descripcion": d.get("descripcion", ""),
                }
                for d in data["dias"] if d["tiene_ot"]
            ] if data["confirmado"] else [],
        })
    resultado.sort(key=lambda x: (not x["confirmado"], x["nombre"]))
    return jsonify(resultado)


@app.route("/e/<token>")
def empleado(token):
    data = _sesion.get(token)
    if not data:
        return render_template("error.html", mensaje="Link inválido o expirado."), 404
    return render_template("empleado.html", data=data, token=token)


@app.route("/e/<token>/confirmar", methods=["POST"])
def confirmar(token):
    data = _sesion.get(token)
    if not data:
        return render_template("error.html", mensaje="Token inválido."), 404

    # Guardar descripción por día
    for dia in data["dias"]:
        if dia["tiene_ot"]:
            key = f"desc_{dia['fecha']}"
            dia["descripcion"] = request.form.get(key, "").strip()

    data["confirmado"]    = True
    data["confirmado_en"] = datetime.now().isoformat()
    _guardar_sesion(_sesion)

    # Guardar confirmación en archivo
    out_dir = Path("confirmaciones")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"{data['legajo']}_{ts}.json"
    out_file.write_text(
        json.dumps({
            "legajo":        data["legajo"],
            "nombre":        data["nombre"],
            "departamento":  data["departamento"],
            "confirmado_en": data["confirmado_en"],
            "totales":       data["totales"],
            "dias": [
                {
                    "fecha":       d["fecha"],
                    "ot50":        d["ot50"],
                    "ot100":       d["ot100"],
                    "descripcion": d.get("descripcion", ""),
                }
                for d in data["dias"] if d["tiene_ot"]
            ],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return render_template("confirmado.html", nombre=data["nombre"])


# ─────────────────────────────────────────────
# Arranque
# ─────────────────────────────────────────────
if __name__ == "__main__":
    hostname = socket.gethostname()
    try:
        ip = socket.gethostbyname(hostname)
    except Exception:
        ip = "127.0.0.1"
    print(f"\n  Supervisor:  http://{ip}:5000")
    print(f"  (también):   http://localhost:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
