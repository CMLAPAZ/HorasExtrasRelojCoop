# -*- coding: utf-8 -*-
import os, re, urllib.parse, sqlite3
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
import pandas as pd
import secrets
import json
from datetime import datetime, timedelta
from pathlib import Path
import socket

from procesador import procesar_fichadas, aplanar_registros_por_tramo

app = Flask(__name__)
app.secret_key   = os.environ.get("SECRET_KEY",      "cm_horas_secret_2026")
SUPERVISOR_PASS  = os.environ.get("SUPERVISOR_PASS",  "cm2026")
FIRMA_SUPERVISOR = os.environ.get("FIRMA_SUPERVISOR", "CM - Carola Martin")
# URL base para links de WhatsApp — si está vacío usa el host del request
WA_BASE_URL = os.environ.get("WA_BASE_URL", "")

SESION_FILE    = Path("sesion.json")
CONFIRM_DIR    = Path("confirmaciones")
SEMANAS_DIR    = Path("semanas")
PERIODOS_DIR   = Path("periodos")
DATOS_DIR      = Path("datos")
DB_FILE        = DATOS_DIR / "cierres.db"
TELEFONOS_FILE = Path("recursos/telefonos.json")

# Prefijos de área por legajo (excepciones a la regla general)
_AREA_CODES = {100: "343", 141: "3435"}
_AREA_DEFAULT = "3437"


# ═══════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════
def _autenticado():
    return session.get("auth") is True

def _requiere_auth():
    return redirect(url_for("login", next=request.path))


# ═══════════════════════════════════════════════
# PERSISTENCIA
# ═══════════════════════════════════════════════
def _cargar_sesion():
    if SESION_FILE.exists():
        try:
            return json.loads(SESION_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _guardar_sesion(s):
    SESION_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

def _cargar_metadata():
    f = SEMANAS_DIR / "metadata.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"semana_actual": 0, "semanas": []}

def _guardar_metadata(m):
    SEMANAS_DIR.mkdir(exist_ok=True)
    (SEMANAS_DIR / "metadata.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8"
    )

def _get_db():
    DATOS_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn

def _init_db():
    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS periodos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                cerrado_en  TEXT,
                semana_desde INTEGER,
                semana_hasta INTEGER,
                archivo     TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS periodo_empleados (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                periodo_id  INTEGER REFERENCES periodos(id),
                legajo      TEXT,
                nombre      TEXT,
                departamento TEXT,
                ot50        TEXT,
                ot100       TEXT,
                comidas     INTEGER DEFAULT 0,
                francos     INTEGER DEFAULT 0,
                tardanzas   INTEGER DEFAULT 0,
                semanas     TEXT,
                confirmado  INTEGER DEFAULT 0
            )
        """)
        # Migración: agregar columnas de fechas si no existen
        for col in ("fecha_desde TEXT DEFAULT ''", "fecha_hasta TEXT DEFAULT ''"):
            try:
                conn.execute(f"ALTER TABLE periodos ADD COLUMN {col}")
            except Exception:
                pass
        conn.commit()
    # Importar JSON viejos si los hay
    if PERIODOS_DIR.exists():
        with _get_db() as conn:
            ya = {r[0] for r in conn.execute("SELECT archivo FROM periodos").fetchall()}
            for f in sorted(PERIODOS_DIR.glob("periodo_*.json")):
                if f.name in ya:
                    continue
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    emps = d.get("empleados", d.get("confirmaciones", []))
                    sems = d.get("semanas", [])
                    cur = conn.execute(
                        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo) VALUES (?,?,?,?)",
                        (d.get("cerrado_en",""), min(sems,default=0), max(sems,default=0), f.name)
                    )
                    pid = cur.lastrowid
                    for e in emps:
                        conn.execute(
                            "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (pid, str(e.get("legajo","")), e.get("nombre",""), e.get("departamento",""),
                             e.get("ot50","0h"), e.get("ot100","0h"),
                             e.get("comidas",0), e.get("francos",0), e.get("tardanzas",0),
                             json.dumps(e.get("semanas",[])),
                             1 if e.get("confirmado") else 0)
                        )
                    conn.commit()
                except Exception:
                    pass

def _guardar_semana_csv(n, df):
    SEMANAS_DIR.mkdir(exist_ok=True)
    df.to_csv(SEMANAS_DIR / f"semana_{n}.csv", index=False, encoding="utf-8")

def _cargar_semana_csv(n):
    f = SEMANAS_DIR / f"semana_{n}.csv"
    return pd.read_csv(f, encoding="utf-8") if f.exists() else None

def _leer_historial(semana=None):
    CONFIRM_DIR.mkdir(exist_ok=True)
    # Solo leer confirmaciones del período activo (semanas en metadata)
    meta = _cargar_metadata()
    semanas_activas = {s.get("numero") for s in meta.get("semanas", [])}
    items = []
    vistos = set()  # legajo + semana ya cubiertos por archivos
    for f in sorted(CONFIRM_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sem_conf = data.get("semana", 0)
            # Ignorar confirmaciones de períodos anteriores
            if semanas_activas and sem_conf not in semanas_activas:
                continue
            if semana is None or sem_conf == semana:
                items.append(data)
                vistos.add((str(data["legajo"]), sem_conf))
        except Exception:
            continue
    # Fallback: empleados confirmados en _sesion sin archivo en confirmaciones/
    for d in _sesion.values():
        if not d.get("confirmado"):
            continue
        key = (str(d["legajo"]), d.get("semana", 0))
        if key in vistos:
            continue
        if semana is not None and d.get("semana") != semana:
            continue
        items.append({
            "legajo":       d["legajo"],
            "nombre":       d["nombre"],
            "departamento": d.get("departamento", ""),
            "confirmado_en": d.get("confirmado_en"),
            "semana":       d.get("semana", 0),
            "semana_depto": d.get("semana_depto", d.get("semana", 0)),
            "totales":      d.get("totales", {}),
            "dias": [
                {"fecha": x["fecha"], "ot50": x["ot50"], "ot100": x["ot100"],
                 "franco": x.get("franco", 0), "comida": x.get("comida", 0),
                 "tipo_dia": x.get("tipo_dia", "normal"),
                 "descripcion": x.get("descripcion", "")}
                for x in d.get("dias", []) if x.get("tiene_ot")
            ],
        })
        vistos.add(key)
    return items

def _cargar_telefonos():
    if TELEFONOS_FILE.exists():
        try:
            return json.loads(TELEFONOS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _guardar_telefonos(t):
    Path("recursos").mkdir(exist_ok=True)
    TELEFONOS_FILE.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")

def _wa_url(legajo, nombre, url, totales=None):
    tel = _cargar_telefonos()
    phone = re.sub(r'\D', '', str(tel.get(str(legajo), "")))
    if not phone:
        return ""
    area = _AREA_CODES.get(int(legajo), _AREA_DEFAULT)
    if WA_BASE_URL:
        from urllib.parse import urlparse
        path = urlparse(url).path
        url  = WA_BASE_URL.rstrip("/") + path
    nombre_corto = nombre.split()[0]
    if totales:
        ot50  = totales.get("ot50",  "0h")
        ot100 = totales.get("ot100", "0h")
        fra   = totales.get("francos",  0)
        com   = totales.get("comidas",  0)
        tar   = totales.get("tardanzas", 0)
        lineas = [f"Hola {nombre_corto}, tus horas extras registradas son:"]
        if ot50  not in ("0h", "0:00", ""): lineas.append(f"• OT 50%: {ot50}")
        if ot100 not in ("0h", "0:00", ""): lineas.append(f"• OT 100%: {ot100}")
        if fra: lineas.append(f"• Francos: {fra}")
        if com: lineas.append(f"• Comidas: {com}")
        if tar: lineas.append(f"• Tardanzas: {tar}")
        if len(lineas) == 1:
            lineas.append("• Sin horas extras este período")
        lineas.append(f"Podés verlas y confirmarlas en: {url}")
        texto = "\n".join(lineas)
    else:
        texto = f"Hola {nombre_corto}, confirmá tus horas extras en este link: {url}"
    msg = urllib.parse.quote(texto)
    return f"https://wa.me/549{area}{phone}?text={msg}"

def _parse_td(s):
    if not s or s == "00:00:00":
        return timedelta(0)
    parts = s.split(":")
    h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
    return timedelta(hours=h, minutes=m, seconds=sec)

def _parse_hm(s):
    """'3h 45m' o '3h' → timedelta"""
    if not s or s == "0h":
        return timedelta(0)
    h = int(re.search(r'(\d+)h', s).group(1)) if re.search(r'(\d+)h', s) else 0
    m = int(re.search(r'(\d+)m', s).group(1)) if re.search(r'(\d+)m', s) else 0
    return timedelta(hours=h, minutes=m)

def _fmt_hm(td):
    total = int(td.total_seconds())
    if total <= 0:
        return "0h"
    h = total // 3600
    m = (total % 3600) // 60
    return f"{h}h {m:02d}m" if m else f"{h}h"

_sesion = _cargar_sesion()
_init_db()

# Recalcular totales de tokens existentes desde sus días (corrige francos mal contados)
_changed = False
for _tok_data in _sesion.values():
    _dias = _tok_data.get("dias", [])
    if not _dias:
        continue
    _ot50 = _ot100 = timedelta(0)
    _com = _fra = _tar = 0
    for _d in _dias:
        _ot50  += _parse_td(_d.get("ot50",  "00:00:00"))
        _ot100 += _parse_td(_d.get("ot100", "00:00:00"))
        _com   += int(_d.get("comida", 0))
        _fra   += int(_d.get("franco", 0))
        _tar   += int(_d.get("tarde",  0))
    _new_t = {"ot50": _fmt_hm(_ot50), "ot100": _fmt_hm(_ot100),
              "comidas": _com, "francos": _fra, "tardanzas": _tar}
    if _tok_data.get("totales") != _new_t:
        _tok_data["totales"] = _new_t
        _changed = True
if _changed:
    _guardar_sesion(_sesion)

# Si no hay semanas activas, limpiar tokens huérfanos de períodos ya cerrados
_meta_inicio = _cargar_metadata()
if not _meta_inicio.get("semanas"):
    if _sesion:
        _sesion.clear()
        _guardar_sesion(_sesion)


# ═══════════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════════
def _preparar_dias(registros):
    dias_dict = {}
    dias_order = []
    for r in registros:
        fecha = r["Fecha"]
        if fecha not in dias_dict:
            dias_order.append(fecha)
            tiene_ot = (
                r["50%"]  != "00:00:00" or r["100%"] != "00:00:00" or
                int(r.get("FRANCO", 0)) > 0 or int(r.get("COMIDA", 0)) > 0
            )
            obs = r.get("Observaciones", "") or ""
            if   "FER"  in obs: tipo_dia = "feriado"
            elif "SAB"  in obs: tipo_dia = "sabado"
            elif "DOM"  in obs: tipo_dia = "domingo"
            elif "PARO" in obs: tipo_dia = "paro"
            else:               tipo_dia = "normal"
            dias_dict[fecha] = {
                "fecha": fecha, "fecha_fmt": fecha[5:],
                "tramos": [],
                "normales": r["Normales"], "ot50": r["50%"], "ot100": r["100%"],
                "comida": int(r.get("COMIDA",0)), "franco": int(r.get("FRANCO",0)),
                "tarde":  int(r.get("Tarde", 0)),
                "tiene_ot": tiene_ot, "tipo_dia": tipo_dia, "descripcion": "",
            }
        e, s = r.get("Entrada",""), r.get("Salida","")
        if e:
            dias_dict[fecha]["tramos"].append({"entrada": e[:5], "salida": s[:5] if s else "—"})
    return [dias_dict[f] for f in dias_order]

def _cargar_excluidos_ot():
    ruta = Path("recursos/excluidos_ot.json")
    try:
        return set(json.loads(ruta.read_text(encoding="utf-8")).get("legajos", []))
    except Exception:
        return set()

def _aplicar_exclusiones_ot(empleados):
    """Marca empleados excluidos sin modificar sus datos."""
    excluidos = _cargar_excluidos_ot()
    for emp in empleados:
        emp["excluido_ot"] = str(emp["legajo"]) in excluidos
    return empleados

def _leer_archivo(fs):
    nombre = (fs.filename or "").lower()
    if nombre.endswith(".xlsx"): return pd.read_excel(fs, engine="openpyxl")
    if nombre.endswith(".xls"):  return pd.read_excel(fs, engine="xlrd")
    for enc in ("utf-8","latin-1","cp1252"):
        for sep in (";",","):
            try:
                fs.seek(0)
                return pd.read_csv(fs, sep=sep, encoding=enc)
            except Exception:
                continue
    raise ValueError("No se pudo leer el archivo.")

def _normalizar_columnas(df):
    aliases = {
        "Nro. de usuario":"Legajo","Fecha/Hora":"FechaHora","Tipo de registro":"Tipo",
        "Fecha_Hora":"FechaHora","Fecha/hora":"FechaHora","fecha_hora":"FechaHora",
        "Depto":"Departamento","depto":"Departamento","departamento":"Departamento",
        "nro_usuario":"Legajo","legajo":"Legajo","nombre":"Nombre","tipo":"Tipo",
    }
    return df.rename(columns={k:v for k,v in aliases.items() if k in df.columns})

def _procesar_empleados(df, departamentos=None):
    """Procesa DataFrame y devuelve (empleados, fecha_desde, fecha_hasta).
    departamentos: lista de nombres a incluir; None = todos."""
    resultados = procesar_fichadas(df)
    empleados  = aplanar_registros_por_tramo(resultados)
    if departamentos:
        empleados = [e for e in empleados if e.get("departamento","") in departamentos]
    empleados = _aplicar_exclusiones_ot(empleados)
    todas_fechas = [r["Fecha"] for emp in empleados for r in emp["registros"] if r["Fecha"]]
    fecha_desde = min(todas_fechas) if todas_fechas else ""
    fecha_hasta = max(todas_fechas) if todas_fechas else ""
    return empleados, fecha_desde, fecha_hasta

def _crear_tokens(empleados, semana_n, semana_depto, base_url):
    tokens_creados = []
    links = []
    for emp in empleados:
        token = secrets.token_urlsafe(10)
        tokens_creados.append(token)
        dias_prep = _preparar_dias(emp["registros"])
        ot50 = ot100 = timedelta(0)
        comidas = francos = tardanzas = 0
        excluido = emp.get("excluido_ot", False)
        for d in dias_prep:
            if not excluido:
                ot50  += _parse_td(d["ot50"])
                ot100 += _parse_td(d["ot100"])
            comidas   += int(d.get("comida", 0))
            francos   += int(d.get("franco", 0))
            tardanzas += int(d.get("tarde",  0))
        _sesion[token] = {
            "legajo": emp["legajo"], "nombre": emp["nombre"],
            "departamento": emp["departamento"],
            "excluido_ot": excluido,
            "dias": dias_prep,
            "totales": {
                "ot50": _fmt_hm(ot50), "ot100": _fmt_hm(ot100),
                "comidas": comidas, "francos": francos, "tardanzas": tardanzas,
            },
            "confirmado": False, "confirmado_en": None,
            "semana": semana_n,
            "semana_depto": semana_depto,
        }
        emp_url = f"{base_url}/e/{token}"
        links.append({"legajo": emp["legajo"], "nombre": emp["nombre"],
                       "url": emp_url,
                       "wa_url": _wa_url(emp["legajo"], emp["nombre"], emp_url,
                                         totales=_sesion[token].get("totales"))})
    return tokens_creados, links


# ═══════════════════════════════════════════════
# RUTAS PÚBLICAS (empleados)
# ═══════════════════════════════════════════════
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
    for dia in data["dias"]:
        if dia["tiene_ot"]:
            dia["descripcion"] = request.form.get(f"desc_{dia['fecha']}", "").strip()
    data["confirmado"]    = True
    data["confirmado_en"] = datetime.now().isoformat()
    _guardar_sesion(_sesion)
    CONFIRM_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (CONFIRM_DIR / f"{data['legajo']}_{ts}.json").write_text(
        json.dumps({
            "legajo": data["legajo"], "nombre": data["nombre"],
            "departamento": data["departamento"],
            "confirmado_en": data["confirmado_en"],
            "semana": data.get("semana", 0),
            "semana_depto": data.get("semana_depto", data.get("semana", 0)),
            "totales": data["totales"],
            "dias": [
                {"fecha": d["fecha"], "ot50": d["ot50"], "ot100": d["ot100"],
                 "franco": d.get("franco",0), "comida": d.get("comida",0),
                 "tipo_dia": d.get("tipo_dia","normal"), "descripcion": d.get("descripcion","")}
                for d in data["dias"] if d["tiene_ot"]
            ],
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return render_template("confirmado.html", nombre=data["nombre"])


# ═══════════════════════════════════════════════
# LOGIN / LOGOUT
# ═══════════════════════════════════════════════
@app.route("/login", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == SUPERVISOR_PASS:
            session["auth"] = True
            return redirect(request.args.get("next") or url_for("index"))
        error = "Contraseña incorrecta."
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ═══════════════════════════════════════════════
# RUTAS SUPERVISOR (protegidas)
# ═══════════════════════════════════════════════
@app.route("/")
def index():
    if not _autenticado(): return _requiere_auth()
    return render_template("supervisor.html")


@app.route("/telefonos/upload", methods=["POST"])
def telefonos_upload():
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    if "archivo" not in request.files: return jsonify({"error":"No se recibió archivo"}), 400
    try:
        df = _leer_archivo(request.files["archivo"])
        df.columns = [str(c).strip() for c in df.columns]
        leg_col = next((c for c in df.columns if "legajo" in c.lower()), df.columns[0])
        tel_col = next((c for c in df.columns if "tel" in c.lower() or "cel" in c.lower()), df.columns[-1])
        telefonos = {}
        for _, row in df.iterrows():
            leg = str(row[leg_col]).strip().split(".")[0]
            tel = str(row[tel_col]).strip().split(".")[0]
            if leg and leg not in ("nan","") and tel and tel not in ("nan",""):
                telefonos[leg] = tel
        _guardar_telefonos(telefonos)
        return jsonify({"ok": True, "total": len(telefonos)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/detectar-departamentos", methods=["POST"])
def detectar_departamentos():
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    if "csv" not in request.files: return jsonify({"error":"No se recibió archivo"}), 400
    try:
        df = _normalizar_columnas(_leer_archivo(request.files["csv"]))
        resultados = procesar_fichadas(df)
        empleados  = aplanar_registros_por_tramo(resultados)
        deptos = sorted(set(e.get("departamento","—") for e in empleados))
        return jsonify({"departamentos": deptos})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/procesar", methods=["POST"])
def procesar():
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    if "csv" not in request.files: return jsonify({"error":"No se recibió archivo"}), 400
    try:
        df = _normalizar_columnas(_leer_archivo(request.files["csv"]))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    departamentos    = request.form.getlist("departamentos") or None
    depto_override   = request.form.get("depto_override", "").strip()

    try:
        empleados, fecha_desde, fecha_hasta = _procesar_empleados(df, departamentos)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not empleados:
        return jsonify({"error": "No se encontraron empleados para los departamentos seleccionados."}), 400

    # Aplicar departamento manual a todos los empleados si se indicó
    if depto_override:
        for emp in empleados:
            emp["departamento"] = depto_override

    meta = _cargar_metadata()
    depto_label = depto_override or (", ".join(departamentos) if departamentos else "Todos")

    # Detectar duplicado por fechas + departamento
    if not request.form.get("force"):
        for s in meta.get("semanas", []):
            if s.get("fecha_desde") == fecha_desde and s.get("fecha_hasta") == fecha_hasta \
               and s.get("departamento", "Todos") == depto_label:
                return jsonify({
                    "duplicado": True,
                    "semana_existente": s["numero"],
                    "fecha_desde": fecha_desde,
                    "fecha_hasta": fecha_hasta,
                    "msg": f"Ya existe la Semana {s['numero']} con las mismas fechas y departamento ({fecha_desde} → {fecha_hasta} / {depto_label}).",
                })

    n = meta["semana_actual"] + 1
    meta["semana_actual"] = n

    # Número de semana por departamento (independiente del global)
    num_depto = sum(1 for s in meta.get("semanas", [])
                    if s.get("departamento", "Todos") == depto_label) + 1

    _guardar_semana_csv(n, df)
    base_url = request.host_url.rstrip("/")
    tokens_creados, links = _crear_tokens(empleados, n, num_depto, base_url)
    _guardar_sesion(_sesion)

    meta["semanas"].append({
        "numero": n, "num_depto": num_depto,
        "fecha_upload": datetime.now().isoformat(),
        "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta,
        "departamento": depto_label,
        "tokens": tokens_creados,
        "legajos": [emp["legajo"] for emp in empleados],
    })
    _guardar_metadata(meta)

    return jsonify({"empleados": links, "semana": n, "num_depto": num_depto,
                    "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta,
                    "departamento": depto_label})


@app.route("/semanas")
def semanas():
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    meta = _cargar_metadata()
    base_url = request.host_url.rstrip("/")
    resultado = []
    for s in meta.get("semanas", []):
        n = s["numero"]
        tokens = [t for t in s.get("tokens",[]) if t in _sesion]
        total      = len(tokens)
        confirmados = sum(1 for t in tokens if _sesion[t].get("confirmado"))
        resultado.append({
            "numero":       n,
            "num_depto":    s.get("num_depto", n),
            "departamento": s.get("departamento","Todos"),
            "fecha_desde":  s.get("fecha_desde",""),
            "fecha_hasta":  s.get("fecha_hasta",""),
            "fecha_upload": s.get("fecha_upload","")[:10],
            "total":        total,
            "confirmados":  confirmados,
        })
    return jsonify(resultado)


@app.route("/semanas/<int:n>/links")
def semana_links(n):
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    base_url = request.host_url.rstrip("/")
    links = [
        {"legajo": d["legajo"], "nombre": d["nombre"],
         "confirmado": d["confirmado"], "url": f"{base_url}/e/{t}",
         "wa_url": _wa_url(d["legajo"], d["nombre"], f"{base_url}/e/{t}",
                           totales=d.get("totales"))}
        for t, d in _sesion.items() if d.get("semana") == n
    ]
    links.sort(key=lambda x: (x["confirmado"], x["nombre"]))
    return jsonify(links)


@app.route("/semanas/<int:n>/eliminar", methods=["POST"])
def eliminar_semana(n):
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    meta = _cargar_metadata()
    sem = next((s for s in meta["semanas"] if s["numero"] == n), None)
    if not sem:
        return jsonify({"error": f"Semana {n} no encontrada"}), 404

    # Eliminar TODOS los tokens de esta semana (incluyendo huérfanos)
    tokens_a_borrar = [t for t, d in _sesion.items() if d.get("semana") == n]
    for t in tokens_a_borrar:
        del _sesion[t]
    _guardar_sesion(_sesion)

    # Eliminar CSV guardado
    csv_path = SEMANAS_DIR / f"semana_{n}.csv"
    if csv_path.exists():
        csv_path.unlink()

    # Quitar de metadata y reordenar contador si era la última
    meta["semanas"] = [s for s in meta["semanas"] if s["numero"] != n]
    if meta["semana_actual"] == n:
        meta["semana_actual"] = max((s["numero"] for s in meta["semanas"]), default=0)
    _guardar_metadata(meta)

    return jsonify({"ok": True})


@app.route("/semanas/<int:n>/regenerar", methods=["POST"])
def regenerar_semana(n):
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    df = _cargar_semana_csv(n)
    if df is None: return jsonify({"error": f"No hay datos guardados para la semana {n}"}), 404

    meta = _cargar_metadata()
    sem_meta = next((s for s in meta["semanas"] if s["numero"] == n), None)
    num_depto = sem_meta.get("num_depto", n) if sem_meta else n
    depto_label = sem_meta.get("departamento", "") if sem_meta else ""

    try:
        empleados, _, _ = _procesar_empleados(_normalizar_columnas(df))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Filtrar a los legajos que realmente pertenecen a esta semana.
    # Necesario porque el CSV guardado puede contener empleados de otros dtos.
    legajos_semana = set(sem_meta.get("legajos", [])) if sem_meta else set()
    if not legajos_semana:
        # Fallback para semanas antiguas sin campo "legajos": derivar desde
        # los tokens activos en sesión ANTES de borrar los pendientes.
        legajos_semana = {d["legajo"] for t, d in _sesion.items()
                          if d.get("semana") == n}
    if legajos_semana:
        empleados = [e for e in empleados if e["legajo"] in legajos_semana]

    if depto_label:
        for emp in empleados:
            emp["departamento"] = depto_label

    # Legajos que ya confirmaron esta semana → no regenerar
    ya_confirmados = {
        d["legajo"] for t, d in _sesion.items()
        if d.get("semana") == n and d.get("confirmado")
    }
    # Eliminar tokens pendientes de esta semana
    pendientes = [t for t, d in _sesion.items()
                  if d.get("semana") == n and not d.get("confirmado")]
    for t in pendientes:
        del _sesion[t]

    empleados_pendientes = [e for e in empleados if e["legajo"] not in ya_confirmados]
    base_url = request.host_url.rstrip("/")
    tokens_nuevos, links = _crear_tokens(empleados_pendientes, n, num_depto, base_url)
    _guardar_sesion(_sesion)

    # Actualizar tokens en metadata (y backfill legajos si faltaba)
    meta = _cargar_metadata()
    for s in meta["semanas"]:
        if s["numero"] == n:
            tokens_vivos = [t for t in s.get("tokens",[])
                            if t in _sesion and _sesion[t].get("confirmado")]
            s["tokens"] = tokens_vivos + tokens_nuevos
            if not s.get("legajos") and legajos_semana:
                s["legajos"] = list(legajos_semana)
            break
    _guardar_metadata(meta)

    return jsonify({"empleados": links, "semana": n,
                    "ya_confirmados": len(ya_confirmados)})


@app.route("/estado")
def estado():
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    resultado = [
        {"legajo": d["legajo"], "nombre": d["nombre"],
         "departamento": d.get("departamento",""),
         "semana": d.get("semana_depto", d.get("semana",0)),
         "confirmado": d["confirmado"],
         "dias": [
             {"fecha": x["fecha"], "ot50": x["ot50"], "ot100": x["ot100"],
              "descripcion": x.get("descripcion","")}
             for x in d["dias"] if x["tiene_ot"]
         ] if d["confirmado"] else []}
        for d in _sesion.values()
    ]
    resultado.sort(key=lambda x: (x["semana"], not x["confirmado"], x["nombre"]))
    return jsonify(resultado)


@app.route("/historial")
def historial():
    if not _autenticado(): return _requiere_auth()
    return render_template("historial.html", items=_leer_historial())


@app.route("/periodo")
def periodo():
    if not _autenticado(): return _requiere_auth()
    meta = _cargar_metadata()
    # Una entrada por semana/upload para que el selector las distinga
    semanas_selector = sorted([
        {"numero": s["numero"],
         "num_depto": s.get("num_depto", s["numero"]),
         "departamento": s.get("departamento", ""),
         "fecha_desde": s.get("fecha_desde", ""),
         "fecha_hasta": s.get("fecha_hasta", ""),
         "archivo": s.get("archivo", "")}
        for s in meta.get("semanas", [])
    ], key=lambda x: x["numero"])
    departamentos = sorted({
        s.get("departamento") or "Todos"
        for s in meta.get("semanas", [])
    })
    return render_template("periodo.html", semanas=semanas_selector,
                           departamentos=departamentos,
                           firma=FIRMA_SUPERVISOR)


def _calcular_periodo(desde, hasta):
    """Acumula totales del período incluyendo no confirmados."""
    por_empleado = {}

    for c in _leer_historial():
        sem = c.get("semana", 0)
        if not (desde <= sem <= hasta):
            continue
        legajo = c["legajo"]
        if legajo not in por_empleado:
            por_empleado[legajo] = {
                "legajo": legajo, "nombre": c["nombre"],
                "departamento": c.get("departamento", ""),
                "ot50": timedelta(0), "ot100": timedelta(0),
                "comidas": 0, "francos": 0, "tardanzas": 0,
                "semanas": [], "dias": [],
                "conf_sem": set(), "pend_sem": set(),
            }
        e = por_empleado[legajo]
        _excl = c.get("excluido_ot") or str(legajo) in _cargar_excluidos_ot()
        if not _excl:
            e["ot50"]  += _parse_hm(c["totales"]["ot50"])
            e["ot100"] += _parse_hm(c["totales"]["ot100"])
        e["comidas"]   += c["totales"].get("comidas", 0)
        e["francos"]   += sum(1 for dia in c.get("dias", []) if dia.get("franco"))
        e["tardanzas"] += c["totales"].get("tardanzas", 0)
        if sem not in e["semanas"]: e["semanas"].append(sem)
        e["dias"].extend(c.get("dias", []))
        e["conf_sem"].add(sem)

    for token, d in _sesion.items():
        sem = d.get("semana", 0)
        if not (desde <= sem <= hasta) or d.get("confirmado"):
            continue
        legajo = d["legajo"]
        tot = d.get("totales", {})
        if legajo not in por_empleado:
            por_empleado[legajo] = {
                "legajo": legajo, "nombre": d["nombre"],
                "departamento": d.get("departamento", ""),
                "ot50": timedelta(0), "ot100": timedelta(0),
                "comidas": 0, "francos": 0, "tardanzas": 0,
                "semanas": [], "dias": [],
                "conf_sem": set(), "pend_sem": set(),
            }
        e = por_empleado[legajo]
        if sem in e["conf_sem"] or sem in e["pend_sem"]:
            continue
        _excl = d.get("excluido_ot") or str(legajo) in _cargar_excluidos_ot()
        if not _excl:
            e["ot50"]  += _parse_hm(tot.get("ot50", "0h"))
            e["ot100"] += _parse_hm(tot.get("ot100", "0h"))
        e["comidas"]   += tot.get("comidas", 0)
        e["francos"]   += sum(1 for dia in d.get("dias", []) if dia.get("franco"))
        e["tardanzas"] += tot.get("tardanzas", 0)
        if sem not in e["semanas"]: e["semanas"].append(sem)
        e["pend_sem"].add(sem)


    return sorted([
        {
            "legajo":      e["legajo"],
            "nombre":      e["nombre"],
            "departamento": e["departamento"],
            "ot50":        _fmt_hm(e["ot50"]),
            "ot100":       _fmt_hm(e["ot100"]),
            "comidas":     e["comidas"],
            "francos":     e["francos"],
            "tardanzas":   e["tardanzas"],
            "semanas":     sorted(set(e["semanas"])),
            "confirmado":  len(e["pend_sem"]) == 0,
            "pendientes":  sorted(e["pend_sem"]),
            "dias":        sorted(e["dias"], key=lambda d: d["fecha"]),
        }
        for e in por_empleado.values()
    ], key=lambda x: x["nombre"])


@app.route("/periodo/resumen")
def periodo_resumen():
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    desde = int(request.args.get("desde", 1))
    hasta = int(request.args.get("hasta", 1))
    return jsonify(_calcular_periodo(desde, hasta))


@app.route("/periodo/exportar")
def periodo_exportar():
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    import csv, io
    from flask import Response
    desde = int(request.args.get("desde", 1))
    hasta = int(request.args.get("hasta", 1))
    resultado = _calcular_periodo(desde, hasta)

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Departamento","Legajo","Nombre","OT 50%","OT 100%",
                "Comidas","Francos","Tardanzas","Semanas","Estado"])
    dep_actual = None
    for e in sorted(resultado, key=lambda x: (x["departamento"] or "—", x["nombre"])):
        dep = e["departamento"] or "—"
        if dep != dep_actual:
            dep_actual = dep
            w.writerow([f"--- {dep} ---", "", "", "", "", "", "", "", "", ""])
        w.writerow([
            dep, e["legajo"], e["nombre"],
            e["ot50"], e["ot100"],
            e["comidas"], e["francos"], e["tardanzas"],
            " ".join(str(s) for s in e["semanas"]),
            "Confirmado" if e["confirmado"] else "Pendiente",
        ])
    out.seek(0)
    nombre_archivo = f"periodo_sem{desde}-{hasta}.csv"
    return Response(
        "﻿" + out.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )


@app.route("/periodo/cerrar", methods=["POST"])
def periodo_cerrar():
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    desde = int(request.form.get("desde", 1))
    hasta = int(request.form.get("hasta", 1))

    resumen = _calcular_periodo(desde, hasta)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ahora = datetime.now().isoformat()
    archivo = f"periodo_{ts}.json"

    # Extraer rango de fechas de las semanas incluidas
    meta = _cargar_metadata()
    _fdlist, _fhlist = [], []
    for s in meta.get("semanas", []):
        nd = s.get("num_depto", s.get("numero", 0))
        try:
            if desde <= int(nd) <= hasta:
                if s.get("fecha_desde"): _fdlist.append(s["fecha_desde"])
                if s.get("fecha_hasta"): _fhlist.append(s["fecha_hasta"])
        except (TypeError, ValueError):
            pass
    fecha_desde_p = min(_fdlist) if _fdlist else ""
    fecha_hasta_p = max(_fhlist) if _fhlist else ""

    # Guardar JSON de respaldo
    PERIODOS_DIR.mkdir(exist_ok=True)
    (PERIODOS_DIR / archivo).write_text(
        json.dumps({"cerrado_en": ahora,
                    "semanas": list(range(desde, hasta+1)),
                    "fecha_desde": fecha_desde_p, "fecha_hasta": fecha_hasta_p,
                    "empleados": resumen},
                   ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Guardar en base de datos
    with _get_db() as conn:
        cur = conn.execute(
            "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, fecha_desde, fecha_hasta) VALUES (?,?,?,?,?,?)",
            (ahora, desde, hasta, archivo, fecha_desde_p, fecha_hasta_p)
        )
        pid = cur.lastrowid
        for e in resumen:
            conn.execute(
                "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (pid, str(e.get("legajo","")), e.get("nombre",""), e.get("departamento",""),
                 e.get("ot50","0h"), e.get("ot100","0h"),
                 e.get("comidas",0), e.get("francos",0), e.get("tardanzas",0),
                 json.dumps(e.get("semanas",[])),
                 1 if e.get("confirmado") else 0)
            )
        conn.commit()

    # Limpiar solo los tokens del rango cerrado
    tokens_borrar = [t for t, d in _sesion.items()
                     if desde <= d.get("semana", 0) <= hasta]
    for t in tokens_borrar:
        del _sesion[t]
    _guardar_sesion(_sesion)

    # Archivar solo las confirmaciones del rango cerrado
    archivo_dir = CONFIRM_DIR / f"periodo_{ts}"
    if CONFIRM_DIR.exists():
        archivo_dir.mkdir(exist_ok=True)
        for f in CONFIRM_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if desde <= data.get("semana", 0) <= hasta:
                    f.rename(archivo_dir / f.name)
            except Exception:
                pass

    # Actualizar metadata: solo quitar las semanas cerradas
    meta = _cargar_metadata()
    meta["semanas"] = [s for s in meta.get("semanas", [])
                       if not (desde <= s.get("numero", 0) <= hasta)]
    meta["semana_actual"] = max((s.get("numero", 0) for s in meta["semanas"]), default=0)
    _guardar_metadata(meta)

    return jsonify({"ok": True, "periodo_archivado": f"periodo_{ts}.json"})


@app.route("/periodos/historial")
def periodos_historial():
    if not _autenticado(): return _requiere_auth()
    with _get_db() as conn:
        rows = conn.execute("""
            SELECT p.id, p.cerrado_en, p.semana_desde, p.semana_hasta,
                   p.fecha_desde, p.fecha_hasta,
                   COUNT(pe.id) as total,
                   SUM(pe.confirmado) as confirmados
            FROM periodos p
            LEFT JOIN periodo_empleados pe ON pe.periodo_id = p.id
            GROUP BY p.id
            ORDER BY p.id DESC
        """).fetchall()
    cierres = []
    for r in rows:
        total = r["total"] or 0
        conf  = r["confirmados"] or 0
        cierres.append({
            "id":          r["id"],
            "cerrado_en":  (r["cerrado_en"] or "")[:16].replace("T", " "),
            "semanas":     list(range(r["semana_desde"], r["semana_hasta"]+1)),
            "fecha_desde": r["fecha_desde"] or "",
            "fecha_hasta": r["fecha_hasta"] or "",
            "total":       total,
            "confirmados": conf,
            "pendientes":  total - conf,
        })
    return render_template("periodos_historial.html", cierres=cierres)


@app.route("/periodos/ver/<int:pid>")
def periodos_ver(pid):
    if not _autenticado(): return _requiere_auth()
    with _get_db() as conn:
        p = conn.execute("SELECT * FROM periodos WHERE id=?", (pid,)).fetchone()
        if not p:
            return "Período no encontrado", 404
        rows = conn.execute(
            "SELECT * FROM periodo_empleados WHERE periodo_id=? ORDER BY departamento, nombre",
            (pid,)
        ).fetchall()
    empleados = []
    for e in rows:
        d = dict(e)
        d["semanas"]   = json.loads(d["semanas"] or "[]")
        d["confirmado"] = bool(d["confirmado"])
        empleados.append(d)
    semanas = list(range(p["semana_desde"], p["semana_hasta"]+1))
    return render_template("periodo_detalle.html",
                           pid=pid,
                           cerrado_en=(p["cerrado_en"] or "")[:16].replace("T", " "),
                           semanas=semanas,
                           empleados=empleados,
                           firma=FIRMA_SUPERVISOR)


@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    if not _autenticado(): return jsonify({"error": "No autorizado"}), 401
    import shutil
    global _sesion

    # Limpiar sesión en memoria y en disco
    _sesion.clear()
    _guardar_sesion(_sesion)

    # Borrar confirmaciones
    if CONFIRM_DIR.exists():
        shutil.rmtree(CONFIRM_DIR)

    # Borrar semanas (CSV + metadata)
    if SEMANAS_DIR.exists():
        shutil.rmtree(SEMANAS_DIR)

    # Borrar periodos JSON
    if PERIODOS_DIR.exists():
        shutil.rmtree(PERIODOS_DIR)

    # Resetear base de datos
    with _get_db() as conn:
        conn.execute("DELETE FROM periodo_empleados")
        conn.execute("DELETE FROM periodos")
        conn.commit()

    return jsonify({"ok": True})


# ═══════════════════════════════════════════════
# ARRANQUE LOCAL
# ═══════════════════════════════════════════════
if __name__ == "__main__":
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "127.0.0.1"
    print(f"\n  Supervisor:  http://{ip}:5000")
    print(f"  Contraseña:  {SUPERVISOR_PASS}\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
