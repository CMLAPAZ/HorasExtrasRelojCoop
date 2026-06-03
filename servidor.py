# -*- coding: utf-8 -*-
import os, re, urllib.parse, sqlite3, unicodedata
from flask import Flask, request, render_template, jsonify, session, redirect, url_for, send_file
import pandas as pd
import secrets
import json
from datetime import datetime, timedelta
from pathlib import Path
import socket
from io import BytesIO

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
_AREA_CODES = {100: "343", 141: "3435", 151: "353"}
_AREA_DEFAULT = "3437"

_DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

def _dia_semana(fecha_str):
    try:
        dt = datetime.strptime(str(fecha_str)[:10], "%Y-%m-%d")
        return _DIAS_ES[dt.weekday()]
    except Exception:
        return ""

@app.template_filter("dia_semana")
def filter_dia_semana(fecha_str):
    return _dia_semana(fecha_str)


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
    """Lee sesion.json (período activo en memoria). Retorna {} si no existe o está corrupto."""
    if SESION_FILE.exists():
        try:
            return json.loads(SESION_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _guardar_sesion(s):
    """Persiste el período activo en sesion.json. No commitear — contiene datos personales."""
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
    """Crea las tablas si no existen y aplica migraciones de columnas nuevas via ALTER TABLE.
    Se llama al arrancar el servidor. Las migraciones usan try/except para ser idempotentes."""
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
        for col in (
            "fecha_desde TEXT DEFAULT ''",
            "fecha_hasta TEXT DEFAULT ''",
            "estado TEXT DEFAULT 'ACTIVO'",
            "fecha_anulacion TEXT DEFAULT ''",
            "motivo_anulacion TEXT DEFAULT ''",
            "usuario_anulacion TEXT DEFAULT ''",
        ):
            try:
                conn.execute(f"ALTER TABLE periodos ADD COLUMN {col}")
            except Exception:
                pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS francos_tomados (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                legajo         TEXT NOT NULL,
                nombre         TEXT NOT NULL,
                tipo           TEXT NOT NULL DEFAULT 'RANGO',
                fecha_desde    TEXT DEFAULT '',
                fecha_hasta    TEXT DEFAULT '',
                fechas_sueltas TEXT DEFAULT '[]',
                dias           INTEGER NOT NULL DEFAULT 1,
                estado         TEXT DEFAULT 'Aprobado',
                observaciones  TEXT DEFAULT '',
                cargado_en     TEXT DEFAULT ''
            )
        """)
        for col in (
            "fecha_emision TEXT DEFAULT ''",
            "autorizado_por TEXT DEFAULT ''",
        ):
            try:
                conn.execute(f"ALTER TABLE francos_tomados ADD COLUMN {col}")
            except Exception:
                pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS francos_saldo_inicial (
                legajo     TEXT PRIMARY KEY,
                nombre     TEXT NOT NULL,
                saldo      INTEGER NOT NULL DEFAULT 0,
                nota       TEXT DEFAULT '',
                cargado_en TEXT DEFAULT ''
            )
        """)
        # Columnas para el cierre mensual (no alteran datos existentes)
        for col in (
            "tomados_al_corte INTEGER DEFAULT 0",
            "gen_extra_al_corte INTEGER DEFAULT 0",
            "fecha_corte TEXT DEFAULT '2026-05-21'",
        ):
            try:
                conn.execute(f"ALTER TABLE francos_saldo_inicial ADD COLUMN {col}")
            except Exception:
                pass
        # Columna para guardar snapshot de saldo anterior (reversión al anular)
        try:
            conn.execute("ALTER TABLE periodos ADD COLUMN saldo_anterior TEXT DEFAULT '{}'")
        except Exception:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS francos_generados (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                legajo       TEXT NOT NULL,
                nombre       TEXT NOT NULL,
                departamento TEXT NOT NULL DEFAULT '',
                descripcion  TEXT NOT NULL DEFAULT '',
                dias         INTEGER NOT NULL DEFAULT 1,
                cargado_en   TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS francos_semana_manual (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                legajo       TEXT NOT NULL,
                nombre       TEXT NOT NULL,
                departamento TEXT NOT NULL DEFAULT '',
                semana_num   INTEGER NOT NULL,
                mes          TEXT NOT NULL DEFAULT '',
                dias         INTEGER NOT NULL DEFAULT 0,
                guardado_en  TEXT DEFAULT '',
                UNIQUE(legajo, semana_num, mes)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS francos_cierre_detalle (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                periodo_id    INTEGER NOT NULL,
                legajo        TEXT NOT NULL,
                nombre        TEXT NOT NULL,
                departamento  TEXT NOT NULL DEFAULT '',
                tipo          TEXT NOT NULL DEFAULT '',
                fecha_desde   TEXT DEFAULT '',
                fecha_hasta   TEXT DEFAULT '',
                fechas_sueltas TEXT DEFAULT '[]',
                dias          INTEGER NOT NULL DEFAULT 0,
                estado        TEXT DEFAULT '',
                fecha_emision TEXT DEFAULT '',
                autorizado_por TEXT DEFAULT '',
                observaciones TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS francos_semana_parcial (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                legajo       TEXT NOT NULL,
                nombre       TEXT NOT NULL,
                departamento TEXT NOT NULL DEFAULT '',
                semana_num   INTEGER NOT NULL,
                dias         INTEGER NOT NULL DEFAULT 0,
                guardado_en  TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS supervisores (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre        TEXT NOT NULL,
                email         TEXT NOT NULL,
                departamentos TEXT NOT NULL DEFAULT '[]',
                activo        INTEGER NOT NULL DEFAULT 1,
                cargado_en    TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS empleados_extra (
                legajo        TEXT PRIMARY KEY,
                nombre        TEXT NOT NULL,
                departamento  TEXT NOT NULL DEFAULT '',
                activo        INTEGER NOT NULL DEFAULT 1,
                cargado_en    TEXT DEFAULT ''
            )
        """)
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

def _archivos_confirmacion():
    CONFIRM_DIR.mkdir(exist_ok=True)
    return sorted(CONFIRM_DIR.rglob("*.json"), reverse=True)

def _parse_fecha(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None

def _clave_confirmacion(data):
    return (
        _normalizar_departamento_web(data.get("departamento", "") or "Todos"),
        str(data.get("legajo", "")),
        data.get("semana", 0),
    )

def _fechas_confirmacion(data):
    fechas = []
    for d in data.get("dias", []) or []:
        f = _parse_fecha(d.get("fecha", ""))
        if f:
            fechas.append(f)
    return fechas

def _resolver_semana_confirmacion(data, meta):
    sem_conf = data.get("semana", 0)
    depto_conf = _normalizar_departamento_web(data.get("departamento", "") or "Todos")
    for s in meta.get("semanas", []):
        if s.get("numero") == sem_conf and _normalizar_departamento_web(s.get("departamento", "") or "Todos") == depto_conf:
            return sem_conf, s.get("num_depto", sem_conf)

    fechas = _fechas_confirmacion(data)
    if not fechas:
        return sem_conf, data.get("semana_depto", sem_conf)
    desde_conf, hasta_conf = min(fechas), max(fechas)
    for s in meta.get("semanas", []):
        if _normalizar_departamento_web(s.get("departamento", "") or "Todos") != depto_conf:
            continue
        desde_sem = _parse_fecha(s.get("fecha_desde", ""))
        hasta_sem = _parse_fecha(s.get("fecha_hasta", ""))
        if desde_sem and hasta_sem and desde_conf <= hasta_sem and hasta_conf >= desde_sem:
            return s.get("numero", sem_conf), s.get("num_depto", s.get("numero", sem_conf))
    return sem_conf, data.get("semana_depto", sem_conf)

def _legajo_key(x):
    leg = str(x.get("legajo", ""))
    try:
        return int(leg)
    except ValueError:
        return 0

def _score_confirmacion(data):
    dias = data.get("dias", []) or []
    descs = sum(1 for d in dias if str(d.get("descripcion", "")).strip())
    confirmado_en = data.get("confirmado_en", "") or ""
    return (descs, confirmado_en)

def _semana_meta_por_numero(meta, semana, departamento=None):
    departamento = _normalizar_departamento_web(departamento)
    return next((
        s for s in meta.get("semanas", [])
        if s.get("numero") == semana
        and (not departamento or _normalizar_departamento_web(s.get("departamento", "") or "Todos") == departamento)
    ), None)

def _ajustar_confirmacion_a_semana(data, meta, semana, departamento=None):
    sem = _semana_meta_por_numero(meta, semana, departamento)
    if not sem:
        return data
    desde = _parse_fecha(sem.get("fecha_desde", ""))
    hasta = _parse_fecha(sem.get("fecha_hasta", ""))
    if not desde or not hasta:
        return data

    dias = []
    for dia in data.get("dias", []) or []:
        fecha = _parse_fecha(dia.get("fecha", ""))
        if fecha and desde <= fecha <= hasta:
            dias.append(dia)

    if len(dias) == len(data.get("dias", []) or []):
        return data

    data = dict(data)
    data["dias"] = dias
    ot50 = ot100 = timedelta(0)
    comidas = francos = tardanzas = 0
    for dia in dias:
        ot50 += _parse_td(dia.get("ot50", "00:00:00"))
        ot100 += _parse_td(dia.get("ot100", "00:00:00"))
        comidas += int(dia.get("comida", 0))
        francos += int(dia.get("franco", 0))
        tardanzas += int(dia.get("tardanzas", dia.get("tarde", 0)))
    data["totales"] = {
        "ot50": _fmt_hm(ot50),
        "ot100": _fmt_hm(ot100),
        "comidas": comidas,
        "francos": francos,
        "tardanzas": tardanzas,
    }
    return data

def _leer_historial(semana=None, departamento=None):
    CONFIRM_DIR.mkdir(exist_ok=True)
    # Solo leer confirmaciones del período activo (semanas en metadata)
    departamento = _normalizar_departamento_web(departamento)
    meta = _cargar_metadata()
    semanas_activas = {s.get("numero") for s in meta.get("semanas", [])}
    items = []
    vistos = set()  # departamento + legajo + semana ya cubiertos por archivos
    mejores = {}
    for f in _archivos_confirmacion():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            depto_conf = _normalizar_departamento_web(data.get("departamento", "") or "Todos")
            sem_conf, sem_depto = _resolver_semana_confirmacion(data, meta)
            data["semana_original"] = data.get("semana", sem_conf)
            data["semana"] = sem_conf
            data["semana_depto"] = sem_depto
            data = _ajustar_confirmacion_a_semana(data, meta, sem_conf, depto_conf)
            # Ignorar confirmaciones de períodos anteriores
            if semanas_activas and sem_conf not in semanas_activas:
                continue
            if departamento and depto_conf != departamento:
                continue
            if semana is None or sem_depto == semana:
                key = _clave_confirmacion(data)
                actual = mejores.get(key)
                if actual is None or _score_confirmacion(data) > _score_confirmacion(actual):
                    mejores[key] = data
        except Exception:
            continue
    items.extend(sorted(mejores.values(), key=_legajo_key))
    vistos.update(mejores.keys())
    # Fallback: empleados confirmados en _sesion sin archivo en confirmaciones/
    for d in _sesion.values():
        if not d.get("confirmado"):
            continue
        depto_conf = _normalizar_departamento_web(d.get("departamento", "") or "Todos")
        if departamento and depto_conf != departamento:
            continue
        key = _clave_confirmacion(d)
        if key in vistos:
            continue
        if semana is not None and d.get("semana_depto", d.get("semana")) != semana:
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
                 "dia_semana": x.get("dia_semana") or _dia_semana(x["fecha"]),
                 "descripcion": x.get("descripcion", ""),
                 "tramos": x.get("tramos", [])}
                for x in d.get("dias", []) if x.get("tiene_ot")
            ],
        })
        vistos.add(key)
    return sorted(items, key=_legajo_key)

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

def _normalizar_valor_excel(v):
    texto = str(v).strip()
    if texto.lower() in ("nan", "none", ""):
        return ""
    if texto.endswith(".0"):
        texto = texto[:-2]
    return texto

def _wa_url(legajo, nombre, url, totales=None, dias=None):
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
    if dias or totales:
        lineas = [f"Hola {nombre_corto}, tus horas extras registradas son:"]
        if dias:
            for d in dias:
                if not d.get("tiene_ot") and not d.get("ot50") and not d.get("ot100") and not d.get("franco") and not d.get("comida"):
                    continue
                if d.get("ot50") == "00:00:00" and d.get("ot100") == "00:00:00" and not d.get("franco") and not d.get("comida"):
                    continue
                dia_nombre = d.get("dia_semana") or _dia_semana(d.get("fecha", ""))
                fecha_fmt  = d.get("fecha_fmt") or d.get("fecha", "")[5:]
                partes = []
                if d.get("ot50")  and d["ot50"]  != "00:00:00": partes.append(f"{d['ot50'][:5]} (50%)")
                if d.get("ot100") and d["ot100"] != "00:00:00": partes.append(f"{d['ot100'][:5]} (100%)")
                if d.get("franco"):  partes.append("Franco")
                if d.get("comida"):  partes.append("Comida")
                if partes:
                    prefijo = f"{dia_nombre} {fecha_fmt}" if dia_nombre else fecha_fmt
                    lineas.append(f"• {prefijo}: {', '.join(partes)}")
        if len(lineas) == 1 and totales:
            ot50  = totales.get("ot50",  "0h")
            ot100 = totales.get("ot100", "0h")
            fra   = totales.get("francos",  0)
            com   = totales.get("comidas",  0)
            tar   = totales.get("tardanzas", 0)
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

def _snapshot_francos_cierre(conn, pid, fecha_desde, fecha_hasta, legajos=None, departamento=""):
    """Copia francos_tomados del período a francos_cierre_detalle y genera PDF.
    Filtra por legajos del departamento que se está cerrando para no mezclar deptos."""
    if not fecha_desde or not fecha_hasta:
        return
    legajos_norm = [str(l) for l in (legajos or [])]
    if legajos_norm:
        placeholders = ",".join("?" * len(legajos_norm))
        rows = conn.execute(f"""
            SELECT legajo, nombre, tipo, fecha_desde, fecha_hasta,
                   fechas_sueltas, dias, estado, fecha_emision, autorizado_por, observaciones
            FROM francos_tomados
            WHERE fecha_desde <= ? AND COALESCE(NULLIF(fecha_hasta,''), fecha_desde) >= ?
              AND legajo IN ({placeholders})
            ORDER BY CAST(legajo AS INTEGER), fecha_desde
        """, (fecha_hasta, fecha_desde, *legajos_norm)).fetchall()
    else:
        rows = conn.execute("""
            SELECT legajo, nombre, tipo, fecha_desde, fecha_hasta,
                   fechas_sueltas, dias, estado, fecha_emision, autorizado_por, observaciones
            FROM francos_tomados
            WHERE fecha_desde <= ? AND COALESCE(NULLIF(fecha_hasta,''), fecha_desde) >= ?
            ORDER BY CAST(legajo AS INTEGER), fecha_desde
        """, (fecha_hasta, fecha_desde)).fetchall()
    depto_visible = _nombre_departamento_visible(departamento) if departamento else ""
    for r in rows:
        conn.execute("""
            INSERT INTO francos_cierre_detalle
              (periodo_id, legajo, nombre, departamento, tipo, fecha_desde, fecha_hasta,
               fechas_sueltas, dias, estado, fecha_emision, autorizado_por, observaciones)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (pid, r["legajo"], r["nombre"], depto_visible, r["tipo"],
              r["fecha_desde"] or "", r["fecha_hasta"] or "", r["fechas_sueltas"] or "[]",
              r["dias"], r["estado"] or "", r["fecha_emision"] or "",
              r["autorizado_por"] or "", r["observaciones"] or ""))
    francos_list = [{**dict(r), "departamento": depto_visible} for r in rows]
    _generar_pdf_francos_cierre(pid, francos_list, fecha_desde, fecha_hasta)


def _generar_pdf_francos_cierre(pid, francos, fecha_desde, fecha_hasta):
    """Genera PDF con detalle de francos tomados para el cierre."""
    try:
        from fpdf import FPDF
        FONTS_DIR = Path("recursos/fonts")
        FONT_REG  = FONTS_DIR / "DejaVuSans.ttf"
        FONT_BOLD = FONTS_DIR / "DejaVuSans-Bold.ttf"

        class PDF(FPDF):
            def __init__(self):
                super().__init__(orientation="L", unit="mm", format="A4")
                self.set_auto_page_break(auto=True, margin=15)
                self._unicode = False
                if FONT_REG.exists() and FONT_BOLD.exists():
                    try:
                        self.add_font("DejaVu", "",  str(FONT_REG),  uni=True)
                        self.add_font("DejaVu", "B", str(FONT_BOLD), uni=True)
                        self._unicode = True
                    except Exception:
                        pass
            def fam(self): return "DejaVu" if self._unicode else "Helvetica"
            def header(self):
                self.set_font(self.fam(), "B", 12)
                self.cell(0, 9, f"Francos Tomados — Cierre #{pid}   ({fecha_desde} al {fecha_hasta})", ln=1, align="C")
                self.ln(2)
            def footer(self):
                self.set_y(-13)
                self.set_font(self.fam(), "", 7)
                self.cell(0, 8, f"Pag. {self.page_no()}  |  CM_HorasExtras", 0, 0, "C")

        pdf = PDF()
        pdf.add_page()
        f = pdf.fam()
        COLS   = ["Leg.", "Nombre", "Tipo", "Fechas", "Días", "Estado", "Autorizado por", "Obs."]
        ANCHOS = [14,     75,       18,     70,        12,     22,       45,               31]

        def cabecera():
            pdf.set_fill_color(200, 215, 240)
            pdf.set_font(f, "B", 8)
            for col, ancho in zip(COLS, ANCHOS):
                pdf.cell(ancho, 6, col, 1, 0, "C", fill=True)
            pdf.ln()

        cabecera()
        depto_act = None
        for r in francos:
            if pdf.get_y() + 7 > pdf.h - pdf.b_margin:
                pdf.add_page(); cabecera()
            dep = (r.get("departamento") or "").upper()
            if dep != depto_act:
                depto_act = dep
                pdf.set_fill_color(30, 58, 95)
                pdf.set_text_color(224, 234, 248)
                pdf.set_font(f, "B", 8)
                pdf.cell(sum(ANCHOS), 6, f"  {dep}", 1, 1, "L", fill=True)
                pdf.set_text_color(0, 0, 0)
            tipo = r.get("tipo", "")
            if tipo == "UNICO":
                fechas = r.get("fecha_desde", "")
            elif tipo == "RANGO":
                fechas = f"{r.get('fecha_desde','')} → {r.get('fecha_hasta','')}"
            else:
                try:
                    fl = json.loads(r.get("fechas_sueltas") or "[]")
                    fechas = ", ".join(fl)
                except Exception:
                    fechas = r.get("fecha_desde", "")
            pdf.set_font(f, "", 8)
            pdf.cell(ANCHOS[0], 6, str(r.get("legajo","")),        1, 0, "C")
            pdf.cell(ANCHOS[1], 6, r.get("nombre",""),              1, 0, "L")
            pdf.cell(ANCHOS[2], 6, tipo,                            1, 0, "C")
            pdf.cell(ANCHOS[3], 6, fechas,                          1, 0, "L")
            pdf.cell(ANCHOS[4], 6, str(r.get("dias", 0)),           1, 0, "C")
            pdf.cell(ANCHOS[5], 6, r.get("estado",""),              1, 0, "C")
            pdf.cell(ANCHOS[6], 6, r.get("autorizado_por","") or "",1, 0, "L")
            pdf.cell(ANCHOS[7], 6, r.get("observaciones","") or "", 1, 1, "L")

        Path("reportes").mkdir(exist_ok=True)
        ts = fecha_desde.replace("-","") if fecha_desde else datetime.now().strftime("%Y%m%d")
        pdf.output(str(Path(f"reportes/francos_cierre_{pid}_{ts}.pdf")))
    except Exception:
        pass


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

def _pdf_bytes(pdf):
    data = pdf.output(dest="S")
    if isinstance(data, str):
        return data.encode("latin-1")
    return bytes(data)

def _pdf_cell_text(value):
    return "" if value is None else str(value)

def _leer_confirmaciones_cierre(periodo):
    archivo = periodo.get("archivo") or ""
    carpeta = CONFIRM_DIR / Path(archivo).stem
    items = []
    if carpeta.exists():
        for f in sorted(carpeta.glob("*.json")):
            try:
                items.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
    return sorted(items, key=lambda x: (
        _normalizar_departamento_web(x.get("departamento", "")),
        _legajo_key(x),
    ))

def _generar_pdf_confirmaciones_cierre(periodo, empleados):
    from pdf_generator import PDFGeneral

    confirmaciones = _leer_confirmaciones_cierre(periodo)
    confirmados = {
        (_normalizar_departamento_web(c.get("departamento", "")), str(c.get("legajo", "")))
        for c in confirmaciones
    }
    pendientes = [
        e for e in empleados
        if not e.get("confirmado")
        and (_normalizar_departamento_web(e.get("departamento", "")), str(e.get("legajo", ""))) not in confirmados
    ]

    pdf = PDFGeneral()
    pdf.titulo = "Confirmaciones del cierre"
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    fam = "DejaVu" if pdf._unicode else "Helvetica"

    semanas = list(range(periodo["semana_desde"], periodo["semana_hasta"] + 1))
    cerrado = (periodo["cerrado_en"] or "")[:16].replace("T", " ")
    rango = f"{periodo['fecha_desde'] or ''} al {periodo['fecha_hasta'] or ''}".strip()
    estado = periodo["estado"] or "ACTIVO"

    pdf.set_font(fam, "B", 12)
    pdf.cell(0, 8, "Confirmaciones archivadas por cierre", ln=1)
    pdf.set_font(fam, "", 9)
    pdf.cell(0, 6, f"Cierre ID: {periodo['id']}    Estado: {estado}    Cerrado: {cerrado}", ln=1)
    pdf.cell(0, 6, f"Semanas: {', '.join(str(s) for s in semanas)}    Periodo: {rango}", ln=1)
    pdf.ln(3)

    if not confirmaciones:
        pdf.set_font(fam, "B", 10)
        pdf.cell(0, 7, "No hay confirmaciones archivadas para este cierre.", ln=1)
    else:
        depto_actual = None
        for c in confirmaciones:
            depto = c.get("departamento", "") or "-"
            if depto != depto_actual:
                depto_actual = depto
                pdf.ln(1)
                pdf.set_fill_color(224, 231, 255)
                pdf.set_font(fam, "B", 10)
                pdf.cell(0, 7, _pdf_cell_text(depto), border=1, ln=1, fill=True)

            # Salto de página si no hay espacio mínimo para el bloque del empleado
            if pdf.get_y() + 16 > pdf.h - pdf.b_margin:
                pdf.add_page()

            tot = c.get("totales", {})
            pdf.set_font(fam, "B", 9)
            pdf.cell(0, 6, f"{c.get('legajo', '')} - {c.get('nombre', '')}", ln=1)
            pdf.set_font(fam, "", 8)
            pdf.cell(0, 4, f"Confirmado: {(c.get('confirmado_en') or '')[:16].replace('T', ' ')}    Semana: {c.get('semana_depto', c.get('semana', ''))}", ln=1)
            pdf.cell(0, 4, f"OT50: {tot.get('ot50', '0h')}    OT100: {tot.get('ot100', '0h')}    Comidas: {tot.get('comidas', 0)}    Francos: {tot.get('francos', 0)}    Tardanzas: {tot.get('tardanzas', 0)}", ln=1)

            dias = c.get("dias", [])
            if dias:
                pdf.set_font(fam, "B", 7)
                pdf.cell(23, 5, "Fecha", 1)
                pdf.cell(24, 5, "Tipo", 1)
                pdf.cell(20, 5, "OT50", 1)
                pdf.cell(20, 5, "OT100", 1)
                pdf.cell(22, 5, "Marcas", 1)
                pdf.cell(0, 5, "Descripcion", 1, ln=1)
                pdf.set_font(fam, "", 7)
                for d in dias:
                    if pdf.get_y() + 5 > pdf.h - pdf.b_margin:
                        pdf.add_page()
                    marcas = []
                    if d.get("franco"):
                        marcas.append("Franco")
                    if d.get("comida"):
                        marcas.append("Comida")
                    x, y = pdf.get_x(), pdf.get_y()
                    desc = _pdf_cell_text(d.get("descripcion") or "Sin descripcion")
                    pdf.cell(23, 5, _pdf_cell_text(d.get("fecha", "")), 1)
                    pdf.cell(24, 5, _pdf_cell_text(d.get("tipo_dia", "normal")), 1)
                    pdf.cell(20, 5, _pdf_cell_text(d.get("ot50", "")), 1)
                    pdf.cell(20, 5, _pdf_cell_text(d.get("ot100", "")), 1)
                    pdf.cell(22, 5, ", ".join(marcas), 1)
                    pdf.multi_cell(0, 5, desc, 1)
                    if pdf.get_y() < y + 5:
                        pdf.set_y(y + 5)
                    pdf.set_x(x)
            pdf.ln(1)

    if pendientes:
        espacio = pdf.h - pdf.get_y() - pdf.b_margin
        if espacio < 30:
            pdf.add_page()
        else:
            pdf.ln(3)
        pendientes_ord = sorted(pendientes, key=_legajo_key)
        pdf.set_font(fam, "B", 11)
        pdf.cell(0, 7, "Pendientes incluidos en el cierre", ln=1)
        pdf.set_font(fam, "B", 8)
        pdf.cell(22, 6, "Legajo", 1)
        pdf.cell(70, 6, "Nombre", 1)
        pdf.cell(40, 6, "Departamento", 1)
        pdf.cell(20, 6, "OT50", 1)
        pdf.cell(20, 6, "OT100", 1)
        pdf.cell(0, 6, "Semanas", 1, ln=1)
        pdf.set_font(fam, "", 8)
        for e in pendientes_ord:
            if pdf.get_y() + 5 > pdf.h - pdf.b_margin:
                pdf.add_page()
            pdf.cell(22, 5, _pdf_cell_text(e.get("legajo", "")), 1)
            pdf.cell(70, 5, _pdf_cell_text(e.get("nombre", ""))[:35], 1)
            pdf.cell(40, 5, _pdf_cell_text(e.get("departamento", ""))[:20], 1)
            pdf.cell(20, 5, _pdf_cell_text(e.get("ot50", "0h")), 1)
            pdf.cell(20, 5, _pdf_cell_text(e.get("ot100", "0h")), 1)
            pdf.cell(0, 5, ", ".join(str(s) for s in e.get("semanas", [])), 1, ln=1)

    return _pdf_bytes(pdf)


def _generar_pdf_confirmaciones_parcial(todos, info):
    from pdf_generator import PDFGeneral

    pdf = PDFGeneral()
    pdf.titulo = "Horas extras parcial"
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    fam = "DejaVu" if pdf._unicode else "Helvetica"

    depto_label = info.get("departamento_label", "Todos")
    rango       = f"{info.get('fecha_desde', '')} al {info.get('fecha_hasta', '')}".strip()
    n_conf      = sum(1 for e in todos if e.get("confirmado"))
    n_pend      = len(todos) - n_conf

    pdf.set_font(fam, "B", 11)
    pdf.cell(0, 7, "Horas Extras - Periodo activo (parcial)", ln=1)
    pdf.set_font(fam, "", 8)
    pdf.cell(0, 5,
        f"Dpto: {depto_label}   Periodo: {rango}   "
        f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}   "
        f"Total: {len(todos)}   Confirmados: {n_conf}   Pendientes: {n_pend}",
        ln=1)
    pdf.ln(2)

    # Sub-tabla días
    IND = 4
    WD  = {"fecha": 22, "tipo": 22, "ot50": 16, "ot100": 16, "marc": 20}

    def _dias_header():
        pdf.set_x(pdf.l_margin + IND)
        pdf.set_fill_color(240, 244, 255)
        pdf.set_font(fam, "B", 6)
        pdf.cell(WD["fecha"], 4, "Fecha",       1, 0, "C", True)
        pdf.cell(WD["tipo"],  4, "Tipo dia",    1, 0, "C", True)
        pdf.cell(WD["ot50"],  4, "OT50",        1, 0, "C", True)
        pdf.cell(WD["ot100"], 4, "OT100",       1, 0, "C", True)
        pdf.cell(WD["marc"],  4, "Marcas",      1, 0, "C", True)
        pdf.cell(0,           4, "Descripcion", 1, 1, "C", True)

    depto_actual = None
    for e in sorted(todos, key=lambda x: (x.get("departamento", ""), _legajo_key(x))):
        depto     = e.get("departamento", "") or "-"
        dias      = e.get("dias", [])
        confirmado = e.get("confirmado", False)

        if pdf.get_y() + 13 > pdf.h - pdf.b_margin:
            pdf.add_page()

        # Separador de departamento
        if depto != depto_actual:
            depto_actual = depto
            pdf.set_fill_color(224, 231, 255)
            pdf.set_font(fam, "B", 8)
            pdf.cell(0, 5, f"  {_pdf_cell_text(depto)}", 0, 1, "L", True)

        # Banda del empleado — color según estado
        sems    = ", ".join(str(s) for s in e.get("semanas", []))
        conf_en = (e.get("confirmado_en") or "")[:16].replace("T", " ")
        estado  = "CONFIRMADO" if confirmado else "PENDIENTE"
        if confirmado:
            pdf.set_fill_color(234, 242, 255)   # azul claro
        else:
            pdf.set_fill_color(255, 249, 235)   # amarillo claro

        pdf.set_font(fam, "B", 7)
        linea1 = (f"{e.get('legajo','')} - {_pdf_cell_text(e.get('nombre',''))}   "
                  f"Sems: {sems}   "
                  f"OT50: {e.get('ot50','0h')}   OT100: {e.get('ot100','0h')}   "
                  f"Com: {e.get('comidas',0)}   Fr: {e.get('francos',0)}")
        # Ancho disponible para la línea principal menos el badge de estado (30mm)
        W_estado = 30
        W_linea  = pdf.w - pdf.l_margin - pdf.r_margin - W_estado
        x0 = pdf.get_x()
        y0 = pdf.get_y()
        pdf.cell(W_linea,  5, linea1,  "LTB", 0, "L", True)
        pdf.set_font(fam, "B", 7)
        if confirmado:
            pdf.set_text_color(22, 101, 52)    # verde
        else:
            pdf.set_text_color(146, 64, 14)    # naranja
        pdf.cell(W_estado, 5, estado, "RTB", 1, "C", True)
        pdf.set_text_color(0, 0, 0)

        # Fecha de confirmación (segunda línea, solo si confirmado)
        if confirmado and conf_en:
            pdf.set_fill_color(234, 242, 255)
            pdf.set_font(fam, "", 6)
            pdf.cell(0, 3, f"    Confirmado el: {conf_en}", 0, 1, "L", True)

        # Detalle de días
        if dias:
            _dias_header()
            pdf.set_font(fam, "", 6)
            for d in dias:
                if pdf.get_y() + 4 > pdf.h - pdf.b_margin:
                    pdf.add_page()
                    _dias_header()
                marcas = []
                if d.get("franco"): marcas.append("Franco")
                if d.get("comida"): marcas.append("Comida")
                desc = _pdf_cell_text(d.get("descripcion") or "")
                pdf.set_x(pdf.l_margin + IND)
                y1 = pdf.get_y()
                pdf.cell(WD["fecha"], 4, _pdf_cell_text(d.get("fecha", "")),    1)
                pdf.cell(WD["tipo"],  4, _pdf_cell_text(d.get("tipo_dia", "")), 1)
                pdf.cell(WD["ot50"],  4, _pdf_cell_text(d.get("ot50", "")),     1, 0, "C")
                pdf.cell(WD["ot100"], 4, _pdf_cell_text(d.get("ot100", "")),    1, 0, "C")
                pdf.cell(WD["marc"],  4, ", ".join(marcas),                     1, 0, "C")
                pdf.multi_cell(0,     4, desc,                                  1)
                if pdf.get_y() < y1 + 4:
                    pdf.set_y(y1 + 4)
        pdf.ln(1)

    return _pdf_bytes(pdf)


def _pendientes_cierre(confirmaciones, empleados):
    confirmados = {
        (_normalizar_departamento_web(c.get("departamento", "")), str(c.get("legajo", "")))
        for c in confirmaciones
    }
    return [
        e for e in empleados
        if not e.get("confirmado")
        and (_normalizar_departamento_web(e.get("departamento", "")), str(e.get("legajo", ""))) not in confirmados
    ]

def _mapa_semanas_visibles_periodo(periodo):
    archivo = periodo.get("archivo") or ""
    json_path = PERIODOS_DIR / archivo
    if not json_path.exists():
        return {}
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    semanas = data.get("semanas") or []
    try:
        visible_desde = int(data.get("semana_visible_desde") or semanas[0])
    except Exception:
        visible_desde = semanas[0] if semanas else 0
    return {int(global_n): visible_desde + i for i, global_n in enumerate(semanas)}

def _aplicar_semanas_visibles(empleados, periodo):
    mapa = _mapa_semanas_visibles_periodo(periodo)
    if not mapa:
        return empleados
    for e in empleados:
        e["semanas"] = [mapa.get(int(s), s) for s in e.get("semanas", [])]
    return empleados

def _restaurar_confirmaciones_desde_archivos(departamento=None):
    departamento = _normalizar_departamento_web(departamento)
    meta = _cargar_metadata()
    restauradas = 0
    mejores = {}
    for f in _archivos_confirmacion():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        depto_conf = _normalizar_departamento_web(data.get("departamento", "") or "Todos")
        if departamento and depto_conf != departamento:
            continue
        sem_conf, sem_depto = _resolver_semana_confirmacion(data, meta)
        data["semana"] = sem_conf
        data["semana_depto"] = sem_depto
        legajo = str(data.get("legajo", ""))
        key = (depto_conf, legajo, sem_conf)
        actual = mejores.get(key)
        if actual is None or _score_confirmacion(data) > _score_confirmacion(actual):
            mejores[key] = data

    for data in mejores.values():
        depto_conf = _normalizar_departamento_web(data.get("departamento", "") or "Todos")
        sem_conf = data.get("semana", 0)
        sem_depto = data.get("semana_depto", sem_conf)
        legajo = str(data.get("legajo", ""))
        for d in _sesion.values():
            if str(d.get("legajo", "")) != legajo:
                continue
            if d.get("semana") != sem_conf:
                continue
            if _normalizar_departamento_web(d.get("departamento", "") or "Todos") != depto_conf:
                continue
            if d.get("confirmado"):
                break
            d["confirmado"] = True
            d["confirmado_en"] = data.get("confirmado_en")
            d["departamento"] = depto_conf
            d["semana_depto"] = sem_depto
            dias_por_fecha = {x.get("fecha"): x for x in data.get("dias", [])}
            for dia in d.get("dias", []):
                confirmado = dias_por_fecha.get(dia.get("fecha"))
                if confirmado:
                    dia["descripcion"] = confirmado.get("descripcion", dia.get("descripcion", ""))
            restauradas += 1
            break
    if restauradas:
        _guardar_sesion(_sesion)
    return restauradas

def _recalcular_totales_token(d):
    ot50 = ot100 = timedelta(0)
    comidas = francos = tardanzas = 0
    excluido = d.get("excluido_ot") or str(d.get("legajo", "")) in _cargar_excluidos_ot()
    for dia in d.get("dias", []):
        if not excluido:
            ot50 += _parse_td(dia.get("ot50", "00:00:00"))
            ot100 += _parse_td(dia.get("ot100", "00:00:00"))
        comidas += int(dia.get("comida", 0))
        francos += int(dia.get("franco", 0))
        tardanzas += int(dia.get("tarde", 0))
    d["totales"] = {
        "ot50": _fmt_hm(ot50),
        "ot100": _fmt_hm(ot100),
        "comidas": comidas,
        "francos": francos,
        "tardanzas": tardanzas,
    }

def _recortar_semana_lunes_domingo(n, departamento=None):
    departamento = _normalizar_departamento_web(departamento)
    tokens = [
        (t, d) for t, d in _sesion.items()
        if d.get("semana") == n
        and (not departamento or _normalizar_departamento_web(d.get("departamento", "") or "Todos") == departamento)
    ]
    fechas = [dia.get("fecha", "") for _, d in tokens for dia in d.get("dias", [])]
    fecha_desde, fecha_hasta = _rango_lunes_domingo(fechas)
    desde = _parse_fecha(fecha_desde)
    hasta = _parse_fecha(fecha_hasta)
    if not desde or not hasta:
        return {"ok": False, "error": "No hay fechas validas para recortar."}

    afectados = 0
    for _, d in tokens:
        dias = [
            dia for dia in d.get("dias", [])
            if (lambda f: f and desde <= f <= hasta)(_parse_fecha(dia.get("fecha", "")))
        ]
        if len(dias) != len(d.get("dias", [])):
            afectados += 1
        d["dias"] = dias
        _recalcular_totales_token(d)
    _guardar_sesion(_sesion)

    meta = _cargar_metadata()
    for s in meta.get("semanas", []):
        if s.get("numero") == n and (not departamento or _normalizar_departamento_web(s.get("departamento", "") or "Todos") == departamento):
            s["fecha_desde"] = fecha_desde
            s["fecha_hasta"] = fecha_hasta
    _guardar_metadata(meta)
    return {"ok": True, "semana": n, "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta, "tokens_afectados": afectados}

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
                "dia_semana": _dia_semana(fecha),
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

def _normalizar_departamento_web(nombre):
    texto = (nombre or "").strip()
    base = unicodedata.normalize("NFKD", texto)
    base = "".join(c for c in base if not unicodedata.combining(c)).lower()
    base = re.sub(r"[^a-z0-9]+", " ", base).strip()
    if base in ("redes", "rede", "red"):
        return "redes"
    if base in ("administracion", "administraciom", "administrativo", "admin"):
        return "administracion"
    if base == "todos":
        return "todos"
    return base

def _nombre_departamento_visible(nombre):
    normalizado = _normalizar_departamento_web(nombre)
    if normalizado == "redes":
        return "Redes"
    if normalizado == "administracion":
        return "Administración"
    return nombre or ""

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
    fecha_desde, fecha_hasta = _rango_lunes_domingo(todas_fechas)
    if fecha_desde and fecha_hasta:
        empleados = _filtrar_empleados_por_rango(empleados, fecha_desde, fecha_hasta)
    empleados = sorted(empleados, key=_legajo_key)
    return empleados, fecha_desde, fecha_hasta

def _rango_lunes_domingo(fechas):
    fechas_dt = sorted(f for f in (_parse_fecha(x) for x in fechas) if f)
    if not fechas_dt:
        return "", ""
    primer_lunes = next((f for f in fechas_dt if f.weekday() == 0), None)
    inicio = primer_lunes or (fechas_dt[0] - timedelta(days=fechas_dt[0].weekday()))
    fin = inicio + timedelta(days=6)
    return inicio.isoformat(), fin.isoformat()

def _filtrar_empleados_por_rango(empleados, fecha_desde, fecha_hasta):
    desde = _parse_fecha(fecha_desde)
    hasta = _parse_fecha(fecha_hasta)
    if not desde or not hasta:
        return empleados
    filtrados = []
    for emp in empleados:
        registros = [
            r for r in emp.get("registros", [])
            if (lambda f: f and desde <= f <= hasta)(_parse_fecha(r.get("Fecha", "")))
        ]
        if registros:
            emp = dict(emp)
            emp["registros"] = registros
            filtrados.append(emp)
    return filtrados

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
                                         totales=_sesion[token].get("totales"),
                                         dias=_sesion[token].get("dias"))})
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
                 "tipo_dia": d.get("tipo_dia","normal"), "descripcion": d.get("descripcion",""),
                 "tramos": d.get("tramos", [])}
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
@app.route("/supervisor")
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
        telefonos_nuevos = {}
        for _, row in df.iterrows():
            leg = _normalizar_valor_excel(row[leg_col])
            tel = _normalizar_valor_excel(row[tel_col])
            if leg and tel:
                telefonos_nuevos[leg] = tel
        if not telefonos_nuevos:
            return jsonify({"error": "No se encontraron telefonos validos en el archivo."}), 400
        telefonos = _cargar_telefonos()
        telefonos.update(telefonos_nuevos)
        _guardar_telefonos(telefonos)
        return jsonify({"ok": True, "total": len(telefonos), "actualizados": len(telefonos_nuevos)})
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

    departamentos = request.form.getlist("departamentos")
    if len(departamentos) != 1:
        return jsonify({"error": "Seleccioná un departamento."}), 400
    depto_original = departamentos[0].strip()
    depto_label = _normalizar_departamento_web(depto_original)
    if not depto_label or depto_label == "todos":
        return jsonify({"error": "Seleccioná un departamento válido."}), 400

    try:
        empleados, fecha_desde, fecha_hasta = _procesar_empleados(df, departamentos)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not empleados:
        return jsonify({"error": "No se encontraron empleados para los departamentos seleccionados."}), 400

    for emp in empleados:
        emp["departamento"] = depto_label

    meta = _cargar_metadata()

    # Detectar duplicado por fechas + departamento
    if not request.form.get("force"):
        for s in meta.get("semanas", []):
            if s.get("fecha_desde") == fecha_desde and s.get("fecha_hasta") == fecha_hasta \
               and s.get("departamento", "Todos") == depto_label:
                nd = s.get("num_depto", s["numero"])
                return jsonify({
                    "duplicado": True,
                    "semana_existente": s["numero"],
                    "num_depto_existente": nd,
                    "fecha_desde": fecha_desde,
                    "fecha_hasta": fecha_hasta,
                    "msg": f"Ya existe la Semana {nd} con las mismas fechas y departamento ({fecha_desde} → {fecha_hasta} / {depto_label}).",
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


@app.route("/semanas/<int:n>/reprocesar", methods=["POST"])
def reprocesar_semana(n):
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    if "csv" not in request.files: return jsonify({"error":"No se recibió archivo"}), 400

    meta = _cargar_metadata()
    semana_existente = next((s for s in meta.get("semanas", []) if s.get("numero") == n), None)
    if not semana_existente:
        return jsonify({"error": f"No existe la semana {n}."}), 404

    # Legajos a actualizar (vacío = todos)
    solo_legajos_raw = request.form.get("solo_legajos", "").strip()
    solo_legajos = {s.strip() for s in solo_legajos_raw.split(",") if s.strip()} if solo_legajos_raw else set()

    try:
        df = _normalizar_columnas(_leer_archivo(request.files["csv"]))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    depto_label = semana_existente.get("departamento", "Todos")
    try:
        empleados_nuevos, fecha_desde, fecha_hasta = _procesar_empleados(df, [depto_label])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not empleados_nuevos:
        return jsonify({"error": "No se encontraron empleados para el departamento."}), 400

    for emp in empleados_nuevos:
        emp["departamento"] = depto_label

    base_url = request.host_url.rstrip("/")
    num_depto = semana_existente.get("num_depto", n)

    # Mapa legajo → nuevo empleado procesado
    nuevos_por_legajo = {str(e["legajo"]): e for e in empleados_nuevos}

    # Mapa legajo → token existente
    token_por_legajo = {
        str(_sesion[t]["legajo"]): t
        for t in semana_existente.get("tokens", [])
        if t in _sesion
    }

    links = []
    tokens_finales = list(semana_existente.get("tokens", []))  # preservar orden original

    # Actualizar solo los legajos indicados (o todos si no se especificaron)
    legajos_a_actualizar = solo_legajos if solo_legajos else set(nuevos_por_legajo.keys())

    for leg in legajos_a_actualizar:
        emp = nuevos_por_legajo.get(leg)
        if not emp:
            continue  # legajo no encontrado en el CSV nuevo, no tocar nada

        dias_prep = _preparar_dias(emp["registros"])
        excluido = emp.get("excluido_ot", False)
        ot50 = ot100 = timedelta(0)
        comidas = francos = tardanzas = 0
        for d in dias_prep:
            if not excluido:
                ot50  += _parse_td(d["ot50"])
                ot100 += _parse_td(d["ot100"])
            comidas   += int(d.get("comida", 0))
            francos   += int(d.get("franco", 0))
            tardanzas += int(d.get("tarde",  0))
        totales = {"ot50": _fmt_hm(ot50), "ot100": _fmt_hm(ot100),
                   "comidas": comidas, "francos": francos, "tardanzas": tardanzas}

        if leg in token_por_legajo:
            # Actualizar datos en el token existente, preservar link y confirmado
            token = token_por_legajo[leg]
            _sesion[token] = {
                **_sesion[token],
                "dias": dias_prep,
                "totales": totales,
                "excluido_ot": excluido,
                "nombre": emp["nombre"],
                "departamento": depto_label,
            }
        else:
            # Empleado nuevo en el CSV: crear token
            token = secrets.token_urlsafe(10)
            _sesion[token] = {
                "legajo": leg, "nombre": emp["nombre"],
                "departamento": depto_label,
                "excluido_ot": excluido,
                "dias": dias_prep, "totales": totales,
                "confirmado": False, "confirmado_en": None,
                "semana": n, "semana_depto": num_depto,
            }
            tokens_finales.append(token)
            token_por_legajo[leg] = token

    # Armar lista de links de todos los empleados de la semana (actualizados y sin tocar)
    for t in tokens_finales:
        if t not in _sesion:
            continue
        d = _sesion[t]
        emp_url = f"{base_url}/e/{t}"
        links.append({"legajo": d["legajo"], "nombre": d["nombre"],
                      "url": emp_url,
                      "wa_url": _wa_url(d["legajo"], d["nombre"], emp_url,
                                        totales=d.get("totales"), dias=d.get("dias"))})

    _guardar_sesion(_sesion)

    # Solo pisar el CSV si se actualizaron todos (parcial no reemplaza el archivo)
    if not solo_legajos:
        _guardar_semana_csv(n, df)
        semana_existente["fecha_desde"] = fecha_desde
        semana_existente["fecha_hasta"] = fecha_hasta
        semana_existente["legajos"] = [emp["legajo"] for emp in empleados_nuevos]

    semana_existente["tokens"] = tokens_finales
    semana_existente["fecha_upload"] = datetime.now().isoformat()
    _guardar_metadata(meta)

    actualizados = list(legajos_a_actualizar & set(nuevos_por_legajo.keys()))
    return jsonify({"empleados": links, "semana": n, "num_depto": num_depto,
                    "fecha_desde": semana_existente.get("fecha_desde", ""),
                    "fecha_hasta": semana_existente.get("fecha_hasta", ""),
                    "departamento": depto_label,
                    "actualizados": actualizados})


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
                           totales=d.get("totales"), dias=d.get("dias"))}
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

    # Borrar francos parciales de esta semana
    with _get_db() as conn:
        conn.execute("DELETE FROM francos_semana_parcial WHERE semana_num=?", (n,))
        conn.commit()

    # Quitar de metadata y reordenar contador si era la última
    meta["semanas"] = [s for s in meta["semanas"] if s["numero"] != n]
    if meta["semana_actual"] == n:
        meta["semana_actual"] = max((s["numero"] for s in meta["semanas"]), default=0)
    _guardar_metadata(meta)

    return jsonify({"ok": True})


@app.route("/semanas/<int:n>/guardar-francos", methods=["POST"])
def guardar_francos_semana(n):
    if not _autenticado(): return jsonify({"error": "No autorizado"}), 401
    ahora = datetime.now().isoformat(timespec="seconds")
    tokens_semana = [(t, d) for t, d in _sesion.items() if d.get("semana") == n]
    if not tokens_semana:
        return jsonify({"error": f"No hay datos de semana {n} en sesión"}), 404
    with _get_db() as conn:
        conn.execute("DELETE FROM francos_semana_parcial WHERE semana_num=?", (n,))
        for _, d in tokens_semana:
            dias = int(d.get("totales", {}).get("francos", 0))
            conn.execute(
                "INSERT INTO francos_semana_parcial (legajo, nombre, departamento, semana_num, dias, guardado_en) VALUES (?,?,?,?,?,?)",
                (str(d.get("legajo", "")), d.get("nombre", ""), d.get("departamento", ""), n, dias, ahora)
            )
        conn.commit()
    guardados = len(tokens_semana)
    return jsonify({"ok": True, "semana": n, "empleados": guardados})


@app.route("/semanas/guardar-francos-todos", methods=["POST"])
def guardar_francos_todos():
    if not _autenticado(): return jsonify({"error": "No autorizado"}), 401
    semanas = {d.get("semana") for d in _sesion.values() if d.get("semana") is not None}
    if not semanas:
        return jsonify({"error": "No hay semanas en sesión"}), 404
    ahora = datetime.now().isoformat(timespec="seconds")
    total_empleados = 0
    with _get_db() as conn:
        # Limpiar todo para evitar que queden semanas eliminadas
        conn.execute("DELETE FROM francos_semana_parcial")
        for n in semanas:
            tokens_semana = [(t, d) for t, d in _sesion.items() if d.get("semana") == n]
            for _, d in tokens_semana:
                dias = int(d.get("totales", {}).get("francos", 0))
                conn.execute(
                    "INSERT INTO francos_semana_parcial (legajo, nombre, departamento, semana_num, dias, guardado_en) VALUES (?,?,?,?,?,?)",
                    (str(d.get("legajo", "")), d.get("nombre", ""), d.get("departamento", ""), n, dias, ahora)
                )
            total_empleados += len(tokens_semana)
        conn.commit()
    return jsonify({"ok": True, "semanas": len(semanas), "empleados": total_empleados})


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


@app.route("/semanas/<int:n>/pdf")
def semana_pdf(n):
    """Genera PDF detallado (día a día) de una semana ya procesada."""
    if not _autenticado(): return _requiere_auth()
    df = _cargar_semana_csv(n)
    if df is None:
        return "No hay datos para esta semana.", 404

    meta       = _cargar_metadata()
    sem_meta   = next((s for s in meta.get("semanas", []) if s["numero"] == n), None)
    num_depto  = sem_meta.get("num_depto", n) if sem_meta else n
    depto_label = sem_meta.get("departamento", "") if sem_meta else ""
    fecha_desde = sem_meta.get("fecha_desde", "") if sem_meta else ""
    fecha_hasta = sem_meta.get("fecha_hasta", "") if sem_meta else ""
    legajos_semana = set(str(l) for l in (sem_meta.get("legajos") or [])) if sem_meta else set()

    try:
        empleados, _, _ = _procesar_empleados(_normalizar_columnas(df))
    except Exception as e:
        return f"Error al procesar datos: {e}", 500

    if legajos_semana:
        empleados = [e for e in empleados if str(e["legajo"]) in legajos_semana]
    if depto_label:
        for emp in empleados:
            emp["departamento"] = depto_label
    if not empleados:
        return "No se encontraron empleados para esta semana.", 404

    depto_visible = _nombre_departamento_visible(depto_label)
    mes_label = f"Semana {num_depto} — {depto_visible} — {fecha_desde} al {fecha_hasta}"
    feriados  = list(_cargar_feriados_config())

    from pdf_generator import generar_pdf_general
    try:
        pdf_data = generar_pdf_general(empleados, mes_label, feriados=feriados)
    except Exception as e:
        return f"Error generando PDF: {e}", 500

    nombre = f"semana_{num_depto}_{depto_label}_{fecha_desde}_{fecha_hasta}.pdf"
    return send_file(BytesIO(pdf_data), mimetype="application/pdf",
                     as_attachment=True, download_name=nombre)


@app.route("/semanas/acumulado/pdf")
def semanas_acumulado_pdf():
    """Genera PDF detallado acumulado de varias semanas (para informar al supervisor al viernes)."""
    if not _autenticado(): return _requiere_auth()
    try:
        desde = int(request.args.get("desde", 1))
        hasta = int(request.args.get("hasta", 1))
    except (TypeError, ValueError):
        return "Parámetros desde/hasta inválidos.", 400

    depto_param   = _normalizar_departamento_web(request.args.get("depto", "").strip())
    meta          = _cargar_metadata()
    semanas_rango = [s for s in meta.get("semanas", [])
                     if desde <= s["numero"] <= hasta
                     and (not depto_param or _normalizar_departamento_web(s.get("departamento","")) == depto_param)]
    if not semanas_rango:
        return "No hay semanas en ese rango.", 404

    feriados        = list(_cargar_feriados_config())
    todos_empleados = {}

    for sem in semanas_rango:
        n_sem       = sem["numero"]
        depto_label  = sem.get("departamento", "")
        legajos_sem  = set(str(l) for l in (sem.get("legajos") or []))
        df = _cargar_semana_csv(n_sem)
        if df is None:
            continue
        try:
            empleados, _, _ = _procesar_empleados(_normalizar_columnas(df))
        except Exception:
            continue
        if legajos_sem:
            empleados = [e for e in empleados if str(e["legajo"]) in legajos_sem]
        if depto_label:
            for emp in empleados:
                emp["departamento"] = depto_label
        for emp in empleados:
            key = str(emp["legajo"])
            if key not in todos_empleados:
                todos_empleados[key] = {
                    "legajo":       emp["legajo"],
                    "nombre":       emp["nombre"],
                    "departamento": emp.get("departamento", ""),
                    "registros":    [],
                    "excluido_ot":  emp.get("excluido_ot", False),
                }
            todos_empleados[key]["registros"].extend(emp.get("registros", []))

    if not todos_empleados:
        return "No se pudieron obtener datos de las semanas seleccionadas.", 500

    data    = list(todos_empleados.values())
    sem_pri = min(semanas_rango, key=lambda s: s["numero"])
    sem_ult = max(semanas_rango, key=lambda s: s["numero"])
    fd      = sem_pri.get("fecha_desde", "")
    fh      = sem_ult.get("fecha_hasta", "")
    depto_label_0 = semanas_rango[0].get("departamento", "")
    depto_visible = _nombre_departamento_visible(depto_label_0)
    mes_label     = f"Acumulado — {depto_visible} — {fd} al {fh}"

    from pdf_generator import generar_pdf_general
    try:
        pdf_data = generar_pdf_general(data, mes_label, feriados=feriados)
    except Exception as e:
        return f"Error generando PDF: {e}", 500

    nombre = f"acumulado_{depto_label_0}_{fd}_{fh}.pdf"
    return send_file(BytesIO(pdf_data), mimetype="application/pdf",
                     as_attachment=True, download_name=nombre)


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


@app.route("/admin/restaurar-confirmaciones", methods=["POST"])
def admin_restaurar_confirmaciones():
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    departamento = request.form.get("departamento", "")
    restauradas = _restaurar_confirmaciones_desde_archivos(departamento)
    return jsonify({"ok": True, "restauradas": restauradas})


@app.route("/admin/recortar-semana", methods=["POST"])
def admin_recortar_semana():
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    departamento = request.form.get("departamento", "")
    try:
        n = int(request.form.get("semana", "0"))
    except ValueError:
        return jsonify({"error": "Semana invalida."}), 400
    try:
        semana_depto = int(request.form.get("semana_depto", "0"))
    except ValueError:
        semana_depto = 0
    if n <= 0 and semana_depto > 0 and departamento:
        depto = _normalizar_departamento_web(departamento)
        meta = _cargar_metadata()
        sem = next((
            s for s in meta.get("semanas", [])
            if _normalizar_departamento_web(s.get("departamento", "") or "Todos") == depto
            and int(s.get("num_depto", s.get("numero", 0))) == semana_depto
        ), None)
        if sem:
            n = int(sem.get("numero", 0))
    if n <= 0:
        return jsonify({"error": "Semana requerida."}), 400
    resultado = _recortar_semana_lunes_domingo(n, departamento)
    status = 200 if resultado.get("ok") else 400
    return jsonify(resultado), status


@app.route("/historial")
def historial():
    if not _autenticado(): return _requiere_auth()
    departamento = _normalizar_departamento_web(request.args.get("departamento", ""))
    semana_raw = request.args.get("semana", "").strip()
    try:
        semana = int(semana_raw) if semana_raw else None
    except ValueError:
        semana = None
    todos = _leer_historial()
    deptos_map = {}
    semanas_map = {}
    for item in todos:
        valor = _normalizar_departamento_web(item.get("departamento", ""))
        if not valor or valor == "todos":
            continue
        deptos_map[valor] = _nombre_departamento_visible(item.get("departamento", ""))
        sem_depto_val = item.get("semana_depto") or item.get("semana")
        if sem_depto_val:
            semanas_map[sem_depto_val] = sem_depto_val
    departamentos = [
        {"valor": valor, "nombre": nombre}
        for valor, nombre in sorted(deptos_map.items(), key=lambda item: item[1])
    ]
    semanas = [
        {"valor": valor, "nombre": nombre}
        for valor, nombre in sorted(semanas_map.items(), key=lambda item: item[1])
    ]
    items = _leer_historial(semana=semana, departamento=departamento)
    return render_template("historial.html", items=items,
                           departamentos=departamentos,
                           departamento_actual=departamento,
                           semanas=semanas,
                           semana_actual=semana)


@app.route("/historial/acumulado")
def historial_acumulado():
    if not _autenticado(): return _requiere_auth()
    departamento = _normalizar_departamento_web(request.args.get("departamento", ""))

    todos_sin_filtro = _leer_historial()
    deptos_map = {}
    for item in todos_sin_filtro:
        valor = _normalizar_departamento_web(item.get("departamento", ""))
        if not valor or valor == "todos":
            continue
        deptos_map[valor] = _nombre_departamento_visible(item.get("departamento", ""))
    departamentos = [
        {"valor": v, "nombre": n}
        for v, n in sorted(deptos_map.items(), key=lambda x: x[1])
    ]

    todos = _leer_historial(departamento=departamento if departamento else None)

    meta = _cargar_metadata()
    sem_fechas = {}
    for s in meta.get("semanas", []):
        depto_s = _normalizar_departamento_web(s.get("departamento", "") or "Todos")
        if not departamento or depto_s == departamento or depto_s == "todos":
            nd = s.get("num_depto", s.get("numero"))
            if nd is not None and nd not in sem_fechas:
                sem_fechas[nd] = {
                    "desde": s.get("fecha_desde", ""),
                    "hasta": s.get("fecha_hasta", ""),
                }

    excluidos = _cargar_excluidos_ot()

    # Mapa (legajo, fecha) → tramos desde _sesion para enriquecer archivos viejos sin tramos
    tramos_sesion = {}
    for d in _sesion.values():
        leg = str(d.get("legajo", ""))
        for dia in d.get("dias", []):
            t = dia.get("tramos", [])
            if leg and dia.get("fecha") and t:
                tramos_sesion[(leg, dia["fecha"])] = t

    por_empleado = {}
    semanas_set = set()

    for item in todos:
        depto = _normalizar_departamento_web(item.get("departamento", "") or "Todos")
        legajo = str(item["legajo"])
        sem = item.get("semana_depto") or item.get("semana", 0)
        semanas_set.add(sem)

        clave = (depto, legajo)
        if clave not in por_empleado:
            por_empleado[clave] = {
                "legajo": legajo,
                "nombre": item["nombre"],
                "departamento": _nombre_departamento_visible(depto),
                "departamento_key": depto,
                "por_semana": {},
                "total": {"ot50": timedelta(0), "ot100": timedelta(0),
                          "comidas": 0, "francos": 0, "tardanzas": 0},
            }

        e = por_empleado[clave]
        excluido = item.get("excluido_ot") or legajo in excluidos
        ot50_td = _parse_hm(item["totales"]["ot50"]) if not excluido else timedelta(0)
        ot100_td = _parse_hm(item["totales"]["ot100"]) if not excluido else timedelta(0)
        comidas = item["totales"].get("comidas", 0)
        francos = sum(1 for d in item.get("dias", []) if d.get("franco"))
        tardanzas = item["totales"].get("tardanzas", 0)
        comentarios = [
            {"fecha": d["fecha"], "texto": d["descripcion"]}
            for d in item.get("dias", [])
            if d.get("descripcion", "").strip()
        ]

        dias_raw = sorted(item.get("dias", []), key=lambda d: d["fecha"])
        # Enriquecer con tramos de _sesion si el archivo de confirmación no los tiene
        dias_raw = [
            dict(d, tramos=d.get("tramos") or tramos_sesion.get((legajo, d["fecha"]), []))
            for d in dias_raw
        ]
        if excluido:
            dias_raw = [dict(d, ot50="00:00:00", ot100="00:00:00") for d in dias_raw]
        e["por_semana"][sem] = {
            "ot50": _fmt_hm(ot50_td),
            "ot100": _fmt_hm(ot100_td),
            "comidas": comidas,
            "francos": francos,
            "tardanzas": tardanzas,
            "comentarios": comentarios,
            "dias_list": dias_raw,
        }
        e["total"]["ot50"] += ot50_td
        e["total"]["ot100"] += ot100_td
        e["total"]["comidas"] += comidas
        e["total"]["francos"] += francos
        e["total"]["tardanzas"] += tardanzas

    empleados_lista = []
    for clave, e in sorted(por_empleado.items(),
                           key=lambda x: _legajo_key({"legajo": x[1]["legajo"]})):
        e["total"]["ot50"] = _fmt_hm(e["total"]["ot50"])
        e["total"]["ot100"] = _fmt_hm(e["total"]["ot100"])
        empleados_lista.append(e)

    semanas = sorted(semanas_set)

    deptos_resultado = {}
    for e in empleados_lista:
        dk = e["departamento_key"]
        if dk not in deptos_resultado:
            deptos_resultado[dk] = {"nombre": e["departamento"], "empleados": []}
        deptos_resultado[dk]["empleados"].append(e)

    return render_template("historial_acumulado.html",
                           deptos=list(deptos_resultado.values()),
                           semanas=semanas,
                           sem_fechas=sem_fechas,
                           departamentos=departamentos,
                           departamento_actual=departamento)


@app.route("/periodo")
def periodo():
    if not _autenticado(): return _requiere_auth()
    meta = _cargar_metadata()
    # Una entrada por semana/upload para que el selector las distinga
    semanas_selector = sorted([
        {"numero": s["numero"],
         "num_depto": s.get("num_depto", s["numero"]),
         "departamento": _normalizar_departamento_web(s.get("departamento", "")),
         "departamento_visible": _nombre_departamento_visible(s.get("departamento", "")),
         "fecha_desde": s.get("fecha_desde", ""),
         "fecha_hasta": s.get("fecha_hasta", ""),
         "archivo": s.get("archivo", "")}
        for s in meta.get("semanas", [])
    ], key=lambda x: x["numero"])
    deptos_map = {}
    for s in meta.get("semanas", []):
        valor = _normalizar_departamento_web(s.get("departamento", ""))
        if not valor or valor == "todos":
            continue
        deptos_map[valor] = _nombre_departamento_visible(s.get("departamento", ""))
    departamentos = [
        {"valor": valor, "nombre": nombre}
        for valor, nombre in sorted(deptos_map.items(), key=lambda item: item[1])
    ]
    return render_template("periodo.html", semanas=semanas_selector,
                           departamentos=departamentos,
                           firma=FIRMA_SUPERVISOR)


def _calcular_periodo(desde, hasta, departamento=None):
    """Acumula totales del período incluyendo no confirmados."""
    departamento = _normalizar_departamento_web(departamento)

    # Mapa semana global → num_depto para mostrar el número visible al usuario
    meta = _cargar_metadata()
    semana_visible = {}
    for s in meta.get("semanas", []):
        depto_s = _normalizar_departamento_web(s.get("departamento", "") or "Todos")
        if not departamento or depto_s == departamento or depto_s == "todos":
            num_g = s.get("numero", 0)
            semana_visible[num_g] = s.get("num_depto", num_g)

    por_empleado = {}

    for c in _leer_historial():
        sem = c.get("semana", 0)
        if not (desde <= sem <= hasta):
            continue
        depto = _normalizar_departamento_web(c.get("departamento", "") or "Todos")
        if departamento and depto != departamento:
            continue
        legajo = str(c["legajo"])
        clave = (depto, legajo)
        if clave not in por_empleado:
            por_empleado[clave] = {
                "legajo": legajo, "nombre": c["nombre"],
                "departamento": _nombre_departamento_visible(depto),
                "ot50": timedelta(0), "ot100": timedelta(0),
                "comidas": 0, "francos": 0, "tardanzas": 0,
                "semanas": [], "dias": [],
                "conf_sem": set(), "pend_sem": set(),
            }
        e = por_empleado[clave]
        _excl = c.get("excluido_ot") or str(legajo) in _cargar_excluidos_ot()
        if not _excl:
            e["ot50"]  += _parse_hm(c["totales"]["ot50"])
            e["ot100"] += _parse_hm(c["totales"]["ot100"])
        e["comidas"]   += c["totales"].get("comidas", 0)
        e["francos"]   += sum(1 for dia in c.get("dias", []) if dia.get("franco"))
        e["tardanzas"] += c["totales"].get("tardanzas", 0)
        sem_vis = semana_visible.get(sem, sem)
        if sem_vis not in e["semanas"]: e["semanas"].append(sem_vis)
        e["dias"].extend(c.get("dias", []))
        e["conf_sem"].add(sem)

    for token, d in _sesion.items():
        sem = d.get("semana", 0)
        if not (desde <= sem <= hasta) or d.get("confirmado"):
            continue
        depto = _normalizar_departamento_web(d.get("departamento", "") or "Todos")
        if departamento and depto != departamento:
            continue
        legajo = str(d["legajo"])
        clave = (depto, legajo)
        tot = d.get("totales", {})
        if clave not in por_empleado:
            por_empleado[clave] = {
                "legajo": legajo, "nombre": d["nombre"],
                "departamento": _nombre_departamento_visible(depto),
                "ot50": timedelta(0), "ot100": timedelta(0),
                "comidas": 0, "francos": 0, "tardanzas": 0,
                "semanas": [], "dias": [],
                "conf_sem": set(), "pend_sem": set(),
            }
        e = por_empleado[clave]
        if sem in e["conf_sem"] or sem in e["pend_sem"]:
            continue
        _excl = d.get("excluido_ot") or str(legajo) in _cargar_excluidos_ot()
        if not _excl:
            e["ot50"]  += _parse_hm(tot.get("ot50", "0h"))
            e["ot100"] += _parse_hm(tot.get("ot100", "0h"))
        e["comidas"]   += tot.get("comidas", 0)
        e["francos"]   += sum(1 for dia in d.get("dias", []) if dia.get("franco"))
        e["tardanzas"] += tot.get("tardanzas", 0)
        sem_vis = semana_visible.get(sem, sem)
        if sem_vis not in e["semanas"]: e["semanas"].append(sem_vis)
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
    ], key=lambda x: _legajo_key(x))


@app.route("/periodo/resumen")
def periodo_resumen():
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    desde = int(request.args.get("desde", 1))
    hasta = int(request.args.get("hasta", 1))
    departamento = _normalizar_departamento_web(request.args.get("departamento", ""))
    fecha_desde = request.args.get("fecha_desde", "").strip()
    fecha_hasta = request.args.get("fecha_hasta", "").strip()
    if not departamento or not fecha_desde or not fecha_hasta:
        return jsonify({"error": "Departamento y rango de fechas requeridos."}), 400
    return jsonify(_calcular_periodo(desde, hasta, departamento))


@app.route("/periodo/exportar")
def periodo_exportar():
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    import csv, io
    from flask import Response
    desde = int(request.args.get("desde", 1))
    hasta = int(request.args.get("hasta", 1))
    departamento = _normalizar_departamento_web(request.args.get("departamento", ""))
    fecha_desde = request.args.get("fecha_desde", "").strip()
    fecha_hasta = request.args.get("fecha_hasta", "").strip()
    if not departamento or not fecha_desde or not fecha_hasta:
        return jsonify({"error": "Departamento y rango de fechas requeridos."}), 400
    resultado = _calcular_periodo(desde, hasta, departamento)

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


@app.route("/periodo/confirmaciones_pdf")
def periodo_confirmaciones_pdf():
    if not _autenticado(): return _requiere_auth()
    try:
        desde = int(request.args.get("desde", 1))
        hasta = int(request.args.get("hasta", 1))
    except ValueError:
        return "Parámetros inválidos.", 400
    departamento = _normalizar_departamento_web(request.args.get("departamento", ""))
    fecha_desde  = request.args.get("fecha_desde", "").strip()
    fecha_hasta  = request.args.get("fecha_hasta", "").strip()
    if not departamento or not fecha_desde or not fecha_hasta:
        return "Departamento y rango de fechas requeridos.", 400

    todos = _calcular_periodo(desde, hasta, departamento)

    # Fecha confirmación más reciente por empleado (del historial)
    hist = [c for c in _leer_historial(departamento=departamento)
            if desde <= c.get("semana", 0) <= hasta]
    conf_en_map = {}
    for c in hist:
        leg   = str(c.get("legajo", ""))
        fecha = c.get("confirmado_en") or ""
        if fecha > conf_en_map.get(leg, ""):
            conf_en_map[leg] = fecha

    # Días por legajo desde _sesion — solo filtramos por rango de semanas,
    # sin filtrar departamento (evita desajustes de normalización).
    # Dedup por fecha dentro de cada legajo.
    dias_por_leg = {}
    for d in _sesion.values():
        sem = d.get("semana", 0)
        if not (desde <= sem <= hasta):
            continue
        leg = str(d.get("legajo", ""))
        by_fecha = dias_por_leg.setdefault(leg, {})
        for x in d.get("dias", []):
            if not (x.get("tiene_ot") or x.get("comida") or x.get("franco")):
                continue
            f = x.get("fecha", "")
            # Si ya existe la fecha, mantener el registro con más información
            if f not in by_fecha or x.get("tiene_ot"):
                by_fecha[f] = x

    for e in todos:
        leg = str(e.get("legajo", ""))
        e["confirmado_en"] = conf_en_map.get(leg, "")
        e["dias"] = sorted(
            dias_por_leg.get(leg, {}).values(),
            key=lambda x: x.get("fecha", "")
        )

    info = {
        "departamento_label": _nombre_departamento_visible(departamento),
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
    }
    try:
        pdf_data = _generar_pdf_confirmaciones_parcial(todos, info)
        nombre = f"confirmaciones_{departamento}_{fecha_desde}_{fecha_hasta}.pdf"
        return send_file(BytesIO(pdf_data), mimetype="application/pdf",
                         as_attachment=True, download_name=nombre)
    except Exception as exc:
        return f"Error generando PDF: {exc}", 500


@app.route("/periodo/cerrar", methods=["POST"])
def periodo_cerrar():
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    desde = int(request.form.get("desde", 1))
    hasta = int(request.form.get("hasta", 1))
    departamento = _normalizar_departamento_web(request.form.get("departamento", ""))
    fecha_desde_req = request.form.get("fecha_desde", "").strip()
    fecha_hasta_req = request.form.get("fecha_hasta", "").strip()
    semana_visible_desde = request.form.get("semana_visible_desde", "").strip()
    semana_visible_hasta = request.form.get("semana_visible_hasta", "").strip()
    if not departamento or not fecha_desde_req or not fecha_hasta_req:
        return jsonify({"error": "SeleccionÃ¡ un departamento para cerrar el perÃ­odo."}), 400
    with _get_db() as conn:
        duplicado = conn.execute("""
            SELECT 1
            FROM periodos p
            JOIN periodo_empleados pe ON pe.periodo_id = p.id
            WHERE p.fecha_desde = ?
              AND p.fecha_hasta = ?
              AND pe.departamento = ?
              AND COALESCE(p.estado, 'ACTIVO') <> 'ANULADO'
            LIMIT 1
        """, (fecha_desde_req, fecha_hasta_req, _nombre_departamento_visible(departamento))).fetchone()
    if duplicado:
        return jsonify({"error": "Ya existe un cierre para ese departamento y rango."}), 400

    resumen = _calcular_periodo(desde, hasta, departamento)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ahora = datetime.now().isoformat()
    archivo = f"periodo_{ts}.json"

    # Extraer rango de fechas de las semanas incluidas
    meta = _cargar_metadata()
    _fdlist, _fhlist = [], []
    semanas_cerradas = []
    for s in meta.get("semanas", []):
        depto = _normalizar_departamento_web(s.get("departamento", "") or "Todos")
        if depto != departamento:
            continue
        try:
            n_global = int(s.get("numero", 0))
            if desde <= n_global <= hasta:
                semanas_cerradas.append(n_global)
                if s.get("fecha_desde"): _fdlist.append(s["fecha_desde"])
                if s.get("fecha_hasta"): _fhlist.append(s["fecha_hasta"])
        except (TypeError, ValueError):
            pass
    fecha_desde_p = fecha_desde_req or (min(_fdlist) if _fdlist else "")
    fecha_hasta_p = fecha_hasta_req or (max(_fhlist) if _fhlist else "")
    if not semanas_cerradas:
        return jsonify({"error": "No hay semanas activas de ese departamento en el rango seleccionado."}), 400
    try:
        visible_desde_int = int(semana_visible_desde or semanas_cerradas[0])
    except Exception:
        visible_desde_int = semanas_cerradas[0]
    semanas_visibles_mapa = {
        int(n): visible_desde_int + i
        for i, n in enumerate(semanas_cerradas)
    }

    # Guardar JSON de respaldo
    PERIODOS_DIR.mkdir(exist_ok=True)
    (PERIODOS_DIR / archivo).write_text(
        json.dumps({"cerrado_en": ahora,
                    "estado": "ACTIVO",
                    "departamento": departamento,
                    "semana_visible_desde": semana_visible_desde,
                    "semana_visible_hasta": semana_visible_hasta,
                    "semanas": semanas_cerradas,
                    "fecha_desde": fecha_desde_p, "fecha_hasta": fecha_hasta_p,
                    "empleados": resumen},
                   ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Guardar en base de datos
    with _get_db() as conn:
        cur = conn.execute(
            "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
            (ahora, desde, hasta, archivo, fecha_desde_p, fecha_hasta_p, "ACTIVO")
        )
        pid = cur.lastrowid
        for e in resumen:
            conn.execute(
                "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (pid, str(e.get("legajo","")), e.get("nombre",""), e.get("departamento",""),
                 e.get("ot50","0h"), e.get("ot100","0h"),
                 e.get("comidas",0), e.get("francos",0), e.get("tardanzas",0),
                 json.dumps([semanas_visibles_mapa.get(int(s), s) for s in e.get("semanas",[])]),
                 1 if e.get("confirmado") else 0)
            )
        # Snapshot de francos tomados — solo legajos del departamento cerrado
        legajos_cierre = [str(e.get("legajo", "")) for e in resumen]
        _snapshot_francos_cierre(conn, pid, fecha_desde_p, fecha_hasta_p,
                                 legajos=legajos_cierre, departamento=departamento)
        # Borrar parciales de francos de las semanas cerradas
        conn.execute(
            "DELETE FROM francos_semana_parcial WHERE semana_num BETWEEN ? AND ?",
            (desde, hasta)
        )
        conn.commit()

    # Limpiar solo los tokens del rango cerrado
    tokens_borrar = [t for t, d in _sesion.items()
                     if desde <= d.get("semana", 0) <= hasta
                     and _normalizar_departamento_web(d.get("departamento", "") or "Todos") == departamento]
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
                if (desde <= data.get("semana", 0) <= hasta
                        and _normalizar_departamento_web(data.get("departamento", "") or "Todos") == departamento):
                    f.rename(archivo_dir / f.name)
            except Exception:
                pass

    # Actualizar metadata: solo quitar las semanas cerradas
    meta = _cargar_metadata()
    meta["semanas"] = [
        s for s in meta.get("semanas", [])
        if not (
            desde <= s.get("numero", 0) <= hasta
            and _normalizar_departamento_web(s.get("departamento", "") or "Todos") == departamento
        )
    ]
    meta["semana_actual"] = max((s.get("numero", 0) for s in meta["semanas"]), default=0)
    _guardar_metadata(meta)

    # ── Actualización automática de saldo_inicial ──────────────────────────
    # Se ejecuta DESPUÉS de limpiar sesión y parciales para que _calcular_saldos()
    # devuelva el saldo neto real sin doble conteo.
    try:
        saldos_nuevos = _calcular_saldos()
        legajos_cierre_set = {str(e.get("legajo", "")) for e in resumen}
        ahora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with _get_db() as conn:
            # Guardar snapshot de saldos anteriores para poder revertir al anular
            saldo_ant = {}
            for leg in legajos_cierre_set:
                row = conn.execute(
                    "SELECT saldo, tomados_al_corte, gen_extra_al_corte, fecha_corte "
                    "FROM francos_saldo_inicial WHERE legajo=?", (leg,)
                ).fetchone()
                if row:
                    saldo_ant[leg] = {
                        "saldo":              row["saldo"],
                        "tomados_al_corte":   row["tomados_al_corte"]   or 0,
                        "gen_extra_al_corte": row["gen_extra_al_corte"] or 0,
                        "fecha_corte":        row["fecha_corte"]         or "2026-05-21",
                    }
                else:
                    saldo_ant[leg] = {"saldo": 0, "tomados_al_corte": 0,
                                      "gen_extra_al_corte": 0, "fecha_corte": "2026-05-21"}

            conn.execute(
                "UPDATE periodos SET saldo_anterior=? WHERE id=?",
                (json.dumps(saldo_ant, ensure_ascii=False), pid)
            )

            # Leer totales actuales de tomados y gen_extra para cada legajo del cierre
            tomados_totales = {r["legajo"]: (r["total"] or 0) for r in conn.execute(
                "SELECT legajo, SUM(dias) as total FROM francos_tomados GROUP BY legajo"
            )}
            gen_extra_totales = {}
            for r in conn.execute("SELECT legajo, SUM(dias) as total FROM francos_generados GROUP BY legajo"):
                gen_extra_totales[r["legajo"]] = gen_extra_totales.get(r["legajo"], 0) + (r["total"] or 0)
            for r in conn.execute("SELECT legajo, SUM(dias) as total FROM francos_semana_manual GROUP BY legajo"):
                gen_extra_totales[r["legajo"]] = gen_extra_totales.get(r["legajo"], 0) + (r["total"] or 0)

            # Actualizar saldo_inicial con el saldo actual calculado
            for s in saldos_nuevos:
                leg = str(s["legajo"])
                if leg not in legajos_cierre_set:
                    continue
                emp_resumen = next((e for e in resumen if str(e.get("legajo","")) == leg), None)
                nombre = emp_resumen.get("nombre", s["nombre"]) if emp_resumen else s["nombre"]
                conn.execute("""
                    INSERT INTO francos_saldo_inicial
                        (legajo, nombre, saldo, nota, cargado_en, tomados_al_corte, gen_extra_al_corte, fecha_corte)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(legajo) DO UPDATE SET
                        saldo              = excluded.saldo,
                        nota               = excluded.nota,
                        cargado_en         = excluded.cargado_en,
                        tomados_al_corte   = excluded.tomados_al_corte,
                        gen_extra_al_corte = excluded.gen_extra_al_corte,
                        fecha_corte        = excluded.fecha_corte
                """, (
                    leg, nombre,
                    s["saldo_actual"],
                    f"Actualizado automáticamente al cerrar período #{pid} ({fecha_hasta_p})",
                    ahora_str,
                    tomados_totales.get(leg, 0),
                    gen_extra_totales.get(leg, 0),
                    fecha_hasta_p,
                ))
            conn.commit()
    except Exception as exc_saldo:
        # No fallar el cierre por un error en la actualización del saldo
        import traceback
        print(f"[ADVERTENCIA] Error al actualizar saldo_inicial: {exc_saldo}\n{traceback.format_exc()}")

    return jsonify({"ok": True, "periodo_archivado": f"periodo_{ts}.json"})


@app.route("/periodos/historial")
def periodos_historial():
    if not _autenticado(): return _requiere_auth()
    with _get_db() as conn:
        rows = conn.execute("""
            SELECT p.id, p.cerrado_en, p.semana_desde, p.semana_hasta,
                   p.fecha_desde, p.fecha_hasta,
                   COALESCE(p.estado, 'ACTIVO') as estado,
                   p.fecha_anulacion, p.motivo_anulacion, p.usuario_anulacion,
                   GROUP_CONCAT(DISTINCT pe.departamento) as departamentos,
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
            "estado":      r["estado"] or "ACTIVO",
            "fecha_anulacion": (r["fecha_anulacion"] or "")[:16].replace("T", " "),
            "motivo_anulacion": r["motivo_anulacion"] or "",
            "usuario_anulacion": r["usuario_anulacion"] or "",
            "departamentos": r["departamentos"] or "",
            "total":       total,
            "confirmados": conf,
            "pendientes":  total - conf,
        })
    return render_template("periodos_historial.html", cierres=cierres)


@app.route("/periodos/anular/<int:pid>", methods=["POST"])
def periodo_anular(pid):
    if not _autenticado(): return jsonify({"error":"No autorizado"}), 401
    motivo = request.form.get("motivo", "").strip()
    usuario = session.get("usuario", "") or "sistema"
    ahora = datetime.now().isoformat()

    with _get_db() as conn:
        p = conn.execute("SELECT * FROM periodos WHERE id=?", (pid,)).fetchone()
        if not p:
            return jsonify({"error": "Cierre no encontrado."}), 404
        if (p["estado"] or "ACTIVO") == "ANULADO":
            return jsonify({"error": "El cierre ya estaba anulado."}), 400

        conn.execute("""
            UPDATE periodos
            SET estado='ANULADO',
                fecha_anulacion=?,
                motivo_anulacion=?,
                usuario_anulacion=?
            WHERE id=?
        """, (ahora, motivo, usuario, pid))
        conn.commit()

    archivo = p["archivo"]
    if archivo:
        json_path = PERIODOS_DIR / archivo
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                data["estado"] = "ANULADO"
                data["fecha_anulacion"] = ahora
                data["motivo_anulacion"] = motivo
                data["usuario_anulacion"] = usuario
                json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

    # ── Restaurar saldo_inicial si el cierre tenía snapshot ─────────────────
    try:
        saldo_ant_raw = p["saldo_anterior"] if "saldo_anterior" in p.keys() else None
        if saldo_ant_raw:
            saldo_ant = json.loads(saldo_ant_raw)
            if saldo_ant:
                ahora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with _get_db() as conn:
                    for leg, vals in saldo_ant.items():
                        conn.execute("""
                            UPDATE francos_saldo_inicial
                            SET saldo=?, tomados_al_corte=?, gen_extra_al_corte=?,
                                fecha_corte=?, nota=?, cargado_en=?
                            WHERE legajo=?
                        """, (
                            vals.get("saldo", 0),
                            vals.get("tomados_al_corte", 0),
                            vals.get("gen_extra_al_corte", 0),
                            vals.get("fecha_corte", "2026-05-21"),
                            f"Restaurado al anular período #{pid}",
                            ahora_str,
                            leg,
                        ))
                    conn.commit()
    except Exception as exc_rest:
        print(f"[ADVERTENCIA] Error al restaurar saldo_inicial al anular #{pid}: {exc_rest}")

    return jsonify({"ok": True})


@app.route("/periodos/ver/<int:pid>")
def periodos_ver(pid):
    if not _autenticado(): return _requiere_auth()
    with _get_db() as conn:
        p = conn.execute("SELECT * FROM periodos WHERE id=?", (pid,)).fetchone()
        if not p:
            return "Período no encontrado", 404
        rows = conn.execute(
            "SELECT * FROM periodo_empleados WHERE periodo_id=? ORDER BY departamento, CAST(legajo AS INTEGER)",
            (pid,)
        ).fetchall()
    empleados = []
    for e in rows:
        d = dict(e)
        d["semanas"]   = json.loads(d["semanas"] or "[]")
        d["confirmado"] = bool(d["confirmado"])
        empleados.append(d)
    empleados = _aplicar_semanas_visibles(empleados, dict(p))
    semanas = list(range(p["semana_desde"], p["semana_hasta"]+1))
    fd = p["fecha_desde"] or ""
    fh = p["fecha_hasta"] or ""
    francos_cierre = []
    with _get_db() as conn2:
        rows_ft = conn2.execute("""
            SELECT legajo, nombre, tipo, fecha_desde, fecha_hasta, fechas_sueltas,
                   dias, estado, fecha_emision, autorizado_por, observaciones
            FROM francos_cierre_detalle
            WHERE periodo_id = ?
            ORDER BY departamento, CAST(legajo AS INTEGER), fecha_desde
        """, (pid,)).fetchall()
    for r in rows_ft:
        d = dict(r)
        if d["tipo"] == "SUELTAS":
            try:
                d["fechas_lista"] = json.loads(d["fechas_sueltas"])
            except Exception:
                d["fechas_lista"] = []
        else:
            d["fechas_lista"] = []
        francos_cierre.append(d)
    return render_template("periodo_detalle.html",
                           pid=pid,
                           cerrado_en=(p["cerrado_en"] or "")[:16].replace("T", " "),
                           fecha_desde=fd,
                           fecha_hasta=fh,
                           semanas=semanas,
                           empleados=empleados,
                           francos_cierre=francos_cierre,
                           firma=FIRMA_SUPERVISOR)


@app.route("/periodos/francos_pdf/<int:pid>")
def periodos_francos_pdf(pid):
    if not _autenticado(): return _requiere_auth()
    import glob as _glob
    matches = sorted(_glob.glob(str(Path(f"reportes/francos_cierre_{pid}_*.pdf"))))
    if not matches:
        return "PDF de francos no encontrado para este cierre.", 404
    return send_file(matches[-1], as_attachment=True,
                     download_name=Path(matches[-1]).name)


@app.route("/periodos/confirmaciones_pdf/<int:pid>")
def periodos_confirmaciones_pdf(pid):
    if not _autenticado(): return _requiere_auth()
    with _get_db() as conn:
        p = conn.execute("SELECT * FROM periodos WHERE id=?", (pid,)).fetchone()
        if not p:
            return "Periodo no encontrado", 404
        rows = conn.execute(
            "SELECT * FROM periodo_empleados WHERE periodo_id=? ORDER BY departamento, CAST(legajo AS INTEGER)",
            (pid,)
        ).fetchall()

    periodo = dict(p)
    empleados = []
    for e in rows:
        d = dict(e)
        d["semanas"] = json.loads(d["semanas"] or "[]")
        d["confirmado"] = bool(d["confirmado"])
        empleados.append(d)
    empleados = _aplicar_semanas_visibles(empleados, periodo)

    try:
        pdf_data = _generar_pdf_confirmaciones_cierre(periodo, empleados)
        nombre = f"confirmaciones_cierre_{pid}.pdf"
        return send_file(
            BytesIO(pdf_data),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=nombre,
        )
    except Exception as exc:
        confirmaciones = _leer_confirmaciones_cierre(periodo)
        return render_template(
            "confirmaciones_cierre.html",
            periodo=periodo,
            empleados=empleados,
            confirmaciones=confirmaciones,
            pendientes=_pendientes_cierre(confirmaciones, empleados),
            error_pdf=str(exc),
        )


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
# FRANCOS TOMADOS
# ═══════════════════════════════════════════════
def _calcular_saldos():
    """Saldo por empleado = saldo_inicial + generados_nuevos - tomados_nuevos.
    Las columnas tomados_al_corte, gen_extra_al_corte y fecha_corte permiten que
    el cierre mensual actualice saldo_inicial sin perder ni duplicar datos."""
    with _get_db() as conn:
        iniciales = {}
        for r in conn.execute(
            "SELECT legajo, saldo, tomados_al_corte, gen_extra_al_corte, fecha_corte "
            "FROM francos_saldo_inicial"
        ):
            iniciales[r["legajo"]] = {
                "saldo":              r["saldo"],
                "tomados_al_corte":   r["tomados_al_corte"]   or 0,
                "gen_extra_al_corte": r["gen_extra_al_corte"] or 0,
                "fecha_corte":        r["fecha_corte"]         or "2026-05-21",
            }

        # Todos los generados por períodos cerrados (se filtra por fecha_corte per-empleado abajo)
        all_pe = conn.execute(
            "SELECT pe.legajo, pe.francos, p.fecha_hasta "
            "FROM periodo_empleados pe "
            "JOIN periodos p ON pe.periodo_id = p.id "
            "WHERE COALESCE(p.estado,'ACTIVO') <> 'ANULADO'"
        ).fetchall()

        gen_manual_raw   = {r["legajo"]: (r["total"] or 0) for r in conn.execute("SELECT legajo, SUM(dias) as total FROM francos_generados GROUP BY legajo")}
        gen_parcial      = {r["legajo"]: (r["total"] or 0) for r in conn.execute("SELECT legajo, SUM(dias) as total FROM francos_semana_parcial GROUP BY legajo")}
        gen_manual_sem   = {r["legajo"]: (r["total"] or 0) for r in conn.execute("SELECT legajo, SUM(dias) as total FROM francos_semana_manual GROUP BY legajo")}
        tomados_raw      = {r["legajo"]: (r["total"] or 0) for r in conn.execute("SELECT legajo, SUM(dias) as total FROM francos_tomados GROUP BY legajo")}

    # gen_periodos filtrado por fecha_corte de cada empleado
    gen_periodos_por_emp = {}
    for row in all_pe:
        leg = row["legajo"]
        corte = iniciales.get(leg, {}).get("fecha_corte", "2026-05-21")
        if (row["fecha_hasta"] or "") > corte:
            gen_periodos_por_emp[leg] = gen_periodos_por_emp.get(leg, 0) + (row["francos"] or 0)

    resultado = []
    for emp in _empleados_conocidos():
        leg  = emp["legajo"]
        ini  = iniciales.get(leg, {"saldo": 0, "tomados_al_corte": 0, "gen_extra_al_corte": 0, "fecha_corte": "2026-05-21"})
        si   = ini["saldo"]
        t_corte   = ini["tomados_al_corte"]
        ge_corte  = ini["gen_extra_al_corte"]

        gen_extra_total = gen_manual_raw.get(leg, 0) + gen_manual_sem.get(leg, 0)
        gen = (gen_periodos_por_emp.get(leg, 0)
               + max(0, gen_extra_total - ge_corte)
               + gen_parcial.get(leg, 0))
        tom = max(0, tomados_raw.get(leg, 0) - t_corte)

        resultado.append({
            "legajo":       leg,
            "nombre":       emp["nombre"],
            "departamento": emp["departamento"],
            "saldo_inicial": si,
            "generados":    gen,
            "tomados":      tom,
            "saldo_actual": si + gen - tom,
        })
    return resultado

def _empleados_conocidos():
    """Lista deduplicada de {legajo, nombre, departamento} ordenada por depto y legajo.
    Fuentes (menor a mayor prioridad): empleados_extra → periodo_empleados → sesion.json
    """
    vistos = {}
    with _get_db() as conn:
        # empleados_extra primero (base maestra de depts sin fichadas)
        for row in conn.execute(
            "SELECT legajo, nombre, departamento FROM empleados_extra WHERE activo=1"
        ):
            vistos[str(row["legajo"])] = {"nombre": row["nombre"], "departamento": row["departamento"] or ""}
        # periodos cerrados (sobreescribe si coincide legajo)
        for row in conn.execute("SELECT DISTINCT legajo, nombre, departamento FROM periodo_empleados"):
            vistos[str(row["legajo"])] = {"nombre": row["nombre"], "departamento": row["departamento"] or ""}
    # sesion activa (máxima prioridad, es la más reciente)
    for d in _sesion.values():
        leg = str(d.get("legajo", ""))
        if leg:
            vistos[leg] = {"nombre": d.get("nombre", ""), "departamento": d.get("departamento", "")}
    return sorted(
        [{"legajo": k, "nombre": v["nombre"], "departamento": v["departamento"]} for k, v in vistos.items()],
        key=lambda e: (e["departamento"].lower(), int(e["legajo"]) if e["legajo"].isdigit() else 0)
    )

def _cargar_feriados_config():
    try:
        cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
        from datetime import date as _date
        return {datetime.strptime(f, "%Y-%m-%d").date() for f in cfg.get("feriados", [])}
    except Exception:
        return set()

def _dias_habiles(fecha_desde_str, fecha_hasta_str):
    """Cuenta días hábiles (lun-vie, excluyendo feriados de config.json)."""
    desde = _parse_fecha(fecha_desde_str)
    hasta = _parse_fecha(fecha_hasta_str)
    if not desde or not hasta:
        return 0
    # Normalizar a date (parse_fecha puede devolver datetime o date)
    if isinstance(desde, datetime):
        desde = desde.date()
    if isinstance(hasta, datetime):
        hasta = hasta.date()
    feriados = _cargar_feriados_config()
    total = 0
    cur = desde
    while cur <= hasta:
        if cur.weekday() < 5 and cur not in feriados:
            total += 1
        cur += timedelta(days=1)
    return total

def _fechas_habiles_set(desde, hasta, feriados):
    """Devuelve el conjunto de dates hábiles (lun-vie, no feriado) en [desde, hasta]."""
    if isinstance(desde, datetime): desde = desde.date()
    if isinstance(hasta, datetime): hasta = hasta.date()
    result = set()
    cur = desde
    while cur <= hasta:
        if cur.weekday() < 5 and cur not in feriados:
            result.add(cur)
        cur += timedelta(days=1)
    return result


def _fechas_del_registro(tipo, fecha_desde_str, fecha_hasta_str, fechas_sueltas_json, feriados):
    """Conjunto de dates efectivas de un registro francos_tomados."""
    if tipo == "SUELTAS":
        try:
            lista = json.loads(fechas_sueltas_json or "[]")
        except Exception:
            lista = []
        result = set()
        for s in lista:
            f = _parse_fecha(s)
            if f:
                result.add(f.date() if isinstance(f, datetime) else f)
        return result
    desde = _parse_fecha(fecha_desde_str)
    hasta = _parse_fecha(fecha_hasta_str)
    if not desde or not hasta:
        return set()
    return _fechas_habiles_set(desde, hasta, feriados)


def _es_guardias(conn, legajo):
    """Devuelve True si el empleado pertenece al departamento GUARDIAS."""
    row = conn.execute(
        "SELECT departamento FROM empleados_extra WHERE legajo=? AND activo=1", (str(legajo),)
    ).fetchone()
    if not row:
        return False
    dep = (row["departamento"] or "").upper().strip()
    return dep in ("GUARDIAS", "GUARDIA")

def _validar_franco_nuevo(conn, legajo, tipo, fecha_desde_str, fecha_hasta_str,
                          fechas_sueltas_lista, exclude_id=None):
    """
    Valida que las fechas sean hábiles y no se superpongan con registros existentes.
    Devuelve string con el error, o None si todo está bien.
    Los empleados de GUARDIAS pueden tomar franco cualquier día (feriados y fines de semana incluidos).
    """
    feriados = _cargar_feriados_config()
    guardias = _es_guardias(conn, legajo)

    # Construir el set de fechas nuevas
    if tipo == "SUELTAS":
        nuevas = set()
        for s in fechas_sueltas_lista:
            f = _parse_fecha(s)
            if f:
                if isinstance(f, datetime): f = f.date()
                if not guardias and f.weekday() >= 5:
                    return f"La fecha {f.strftime('%d/%m/%Y')} es fin de semana"
                if not guardias and f in feriados:
                    return f"La fecha {f.strftime('%d/%m/%Y')} es feriado"
                nuevas.add(f)
    elif tipo == "UNICO":
        f = _parse_fecha(fecha_desde_str)
        if not f:
            return "Fecha inválida"
        if isinstance(f, datetime): f = f.date()
        if not guardias and f.weekday() >= 5:
            return f"La fecha {f.strftime('%d/%m/%Y')} es fin de semana"
        if not guardias and f in feriados:
            return f"La fecha {f.strftime('%d/%m/%Y')} es feriado"
        nuevas = {f}
    else:  # RANGO
        desde = _parse_fecha(fecha_desde_str)
        hasta = _parse_fecha(fecha_hasta_str)
        if not desde or not hasta:
            return "Fechas inválidas"
        if guardias:
            # Para guardias contar todos los días corridos
            if isinstance(desde, datetime): desde = desde.date()
            if isinstance(hasta, datetime): hasta = hasta.date()
            nuevas = set()
            cur = desde
            while cur <= hasta:
                nuevas.add(cur)
                cur += timedelta(days=1)
        else:
            nuevas = _fechas_habiles_set(desde, hasta, feriados)

    if not nuevas:
        return "El período no contiene días válidos"

    # Verificar superposición con registros existentes del mismo empleado
    query = "SELECT id, tipo, fecha_desde, fecha_hasta, fechas_sueltas FROM francos_tomados WHERE legajo=?"
    params = [str(legajo)]
    if exclude_id:
        query += " AND id != ?"
        params.append(exclude_id)
    for row in conn.execute(query, params).fetchall():
        existentes = _fechas_del_registro(
            row["tipo"] if isinstance(row, sqlite3.Row) else row[1],
            row["fecha_desde"] if isinstance(row, sqlite3.Row) else row[2],
            row["fecha_hasta"] if isinstance(row, sqlite3.Row) else row[3],
            row["fechas_sueltas"] if isinstance(row, sqlite3.Row) else row[4],
            feriados,
        )
        solapadas = nuevas & existentes
        if solapadas:
            primera = min(solapadas).strftime("%d/%m/%Y")
            return f"El empleado ya tiene franco registrado el {primera}"

    return None


@app.route("/francos")
def francos():
    if not _autenticado(): return _requiere_auth()
    with _get_db() as conn:
        registros = conn.execute(
            "SELECT * FROM francos_tomados ORDER BY cargado_en DESC, id DESC"
        ).fetchall()
    registros = [dict(r) for r in registros]
    for r in registros:
        if r["tipo"] == "SUELTAS":
            try:
                r["fechas_lista"] = json.loads(r["fechas_sueltas"])
            except Exception:
                r["fechas_lista"] = []
        else:
            r["fechas_lista"] = []
    empleados_raw = _empleados_conocidos()
    emp_depto = {e["legajo"]: e["departamento"] for e in empleados_raw}
    for r in registros:
        r["departamento"] = emp_depto.get(r["legajo"], "")
    _reg_dict = {}
    for r in registros:
        dep = r["departamento"] or "Sin departamento"
        _reg_dict.setdefault(dep, []).append(r)
    registros_por_depto = sorted(
        [{"departamento": k, "registros": v} for k, v in _reg_dict.items()],
        key=lambda x: x["departamento"].lower()
    )
    empleados_por_depto = {}
    for e in empleados_raw:
        dep = e["departamento"] or "Sin departamento"
        empleados_por_depto.setdefault(dep, []).append(e)
    empleados_grupos = [{"departamento": k, "empleados": v} for k, v in sorted(empleados_por_depto.items())]
    saldos_raw = _calcular_saldos()
    sf_grupos = {}
    for s in saldos_raw:
        dep = s["departamento"] or "Sin departamento"
        sf_grupos.setdefault(dep, []).append(s)
    saldos_por_depto_f = []
    for k, v in sorted(sf_grupos.items()):
        saldos_por_depto_f.append({
            "departamento":    k,
            "empleados":       v,
            "total_inicial":   sum(e["saldo_inicial"] for e in v),
            "total_generados": sum(e["generados"]     for e in v),
            "total_tomados":   sum(e["tomados"]       for e in v),
            "total_actual":    sum(e["saldo_actual"]  for e in v),
        })
    total_general_f = {
        "inicial":   sum(g["total_inicial"]   for g in saldos_por_depto_f),
        "generados": sum(g["total_generados"] for g in saldos_por_depto_f),
        "tomados":   sum(g["total_tomados"]   for g in saldos_por_depto_f),
        "actual":    sum(g["total_actual"]    for g in saldos_por_depto_f),
    }
    departamentos = sorted({e["departamento"] for e in empleados_raw if e["departamento"]})
    # Deptos manuales con valores guardados por semana/mes
    mes_actual = datetime.now().strftime("%Y-%m")
    with _get_db() as conn:
        gen_manual = [dict(r) for r in conn.execute(
            "SELECT * FROM francos_generados ORDER BY cargado_en DESC, id DESC"
        )]
        emps_extra = conn.execute(
            "SELECT legajo, nombre, departamento FROM empleados_extra WHERE activo=1 ORDER BY departamento, CAST(legajo AS INTEGER)"
        ).fetchall()
        manual_guardados = {}
        for r in conn.execute(
            "SELECT legajo, semana_num, dias FROM francos_semana_manual WHERE mes=?", (mes_actual,)
        ):
            manual_guardados.setdefault(str(r["legajo"]), {})[r["semana_num"]] = r["dias"]
    _DEPTOS_AUTO = {"redes", "administracion"}
    deptos_manuales = {}
    for e in emps_extra:
        dep_norm = _normalizar_departamento_web(e["departamento"] or "")
        if dep_norm in _DEPTOS_AUTO:
            continue
        dep = e["departamento"] or "Sin departamento"
        deptos_manuales.setdefault(dep, []).append({
            "legajo": e["legajo"], "nombre": e["nombre"],
            "semanas": manual_guardados.get(str(e["legajo"]), {})
        })
    deptos_manuales_list = [{"departamento": k, "empleados": v} for k, v in sorted(deptos_manuales.items())]
    return render_template("francos.html",
                           registros=registros,
                           registros_por_depto=registros_por_depto,
                           saldos_por_depto=saldos_por_depto_f,
                           total_general=total_general_f,
                           empleados_grupos=empleados_grupos,
                           departamentos=departamentos,
                           gen_manual=gen_manual,
                           deptos_manuales=deptos_manuales_list,
                           mes_actual=mes_actual)


@app.route("/francos/saldos")
def francos_saldos():
    if not _autenticado(): return _requiere_auth()
    with _get_db() as conn:
        iniciales   = {r["legajo"]: dict(r) for r in conn.execute("SELECT * FROM francos_saldo_inicial")}
        gen_manual  = [dict(r) for r in conn.execute(
            "SELECT * FROM francos_generados ORDER BY cargado_en DESC, id DESC"
        )]
    empleados_raw = _empleados_conocidos()
    por_depto = {}
    for e in empleados_raw:
        dep = e["departamento"] or "Sin departamento"
        por_depto.setdefault(dep, []).append(e)
    empleados_grupos = [{"departamento": dep, "empleados": emps} for dep, emps in sorted(por_depto.items())]
    departamentos = sorted({e["departamento"] for e in empleados_raw if e["departamento"]})
    # Agrupar saldos por departamento
    saldos_raw = _calcular_saldos()
    saldos_grupos = {}
    for s in saldos_raw:
        dep = s["departamento"] or "Sin departamento"
        saldos_grupos.setdefault(dep, []).append(s)
    saldos_por_depto = []
    for k, v in sorted(saldos_grupos.items()):
        saldos_por_depto.append({
            "departamento":    k,
            "empleados":       v,
            "total_inicial":   sum(e["saldo_inicial"] for e in v),
            "total_generados": sum(e["generados"]     for e in v),
            "total_tomados":   sum(e["tomados"]       for e in v),
            "total_actual":    sum(e["saldo_actual"]  for e in v),
        })
    total_general = {
        "inicial":   sum(g["total_inicial"]   for g in saldos_por_depto),
        "generados": sum(g["total_generados"] for g in saldos_por_depto),
        "tomados":   sum(g["total_tomados"]   for g in saldos_por_depto),
        "actual":    sum(g["total_actual"]    for g in saldos_por_depto),
    }
    return render_template("francos_saldos.html",
                           saldos_por_depto=saldos_por_depto,
                           total_general=total_general,
                           iniciales=iniciales,
                           empleados_grupos=empleados_grupos,
                           gen_manual=gen_manual,
                           departamentos=departamentos)


@app.route("/francos/saldos/exportar")
def francos_saldos_exportar():
    if not _autenticado(): return _requiere_auth()
    depto_filtro = request.args.get("depto", "").strip().lower()
    saldos_raw = _calcular_saldos()
    from io import StringIO
    import csv as csv_mod
    si = StringIO()
    w = csv_mod.writer(si, delimiter=";")
    w.writerow(["Departamento", "Legajo", "Nombre", "Saldo inicial", "Generados", "Tomados", "Saldo actual"])
    for s in saldos_raw:
        dep = s.get("departamento") or ""
        if depto_filtro and dep.lower() != depto_filtro:
            continue
        w.writerow([dep, s["legajo"], s["nombre"],
                    s["saldo_inicial"], s["generados"], s["tomados"], s["saldo_actual"]])
    output = si.getvalue().encode("utf-8-sig")
    from flask import Response
    nombre_archivo = f"saldos_francos_{depto_filtro or 'todos'}.csv"
    return Response(output, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={nombre_archivo}"})


@app.route("/francos/saldos/guardar", methods=["POST"])
def francos_saldos_guardar():
    if not _autenticado(): return _requiere_auth()
    legajo = request.form.get("legajo", "").strip()
    nombre = request.form.get("nombre", "").strip()
    try:
        saldo = int(request.form.get("saldo", "0").strip())
    except ValueError:
        saldo = 0
    nota   = request.form.get("nota", "").strip()
    ahora  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not legajo or not nombre:
        return redirect(url_for("francos_saldos") + "?error=datos_requeridos")
    with _get_db() as conn:
        conn.execute("""
            INSERT INTO francos_saldo_inicial (legajo, nombre, saldo, nota, cargado_en)
            VALUES (?,?,?,?,?)
            ON CONFLICT(legajo) DO UPDATE SET nombre=excluded.nombre, saldo=excluded.saldo, nota=excluded.nota, cargado_en=excluded.cargado_en
        """, (legajo, nombre, saldo, nota, ahora))
        conn.commit()
    return redirect(url_for("francos_saldos"))


@app.route("/francos/generados/nuevo", methods=["POST"])
def francos_generados_nuevo():
    if not _autenticado(): return _requiere_auth()
    legajo      = request.form.get("legajo", "").strip()
    nombre      = request.form.get("nombre", "").strip()
    departamento = request.form.get("departamento", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    try:
        dias = int(request.form.get("dias", "1").strip())
    except ValueError:
        dias = 1
    if not legajo or not nombre or dias < 1:
        return redirect(url_for("francos_saldos") + "?error=generados_datos_requeridos")
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _get_db() as conn:
        conn.execute("""
            INSERT INTO francos_generados (legajo, nombre, departamento, descripcion, dias, cargado_en)
            VALUES (?,?,?,?,?,?)
        """, (legajo, nombre, departamento, descripcion, dias, ahora))
        conn.commit()
    return redirect(url_for("francos_saldos"))


@app.route("/francos/generados/eliminar/<int:gen_id>", methods=["POST"])
def francos_generados_eliminar(gen_id):
    if not _autenticado(): return _requiere_auth()
    with _get_db() as conn:
        conn.execute("DELETE FROM francos_generados WHERE id=?", (gen_id,))
        conn.commit()
    return redirect(url_for("francos_saldos"))


@app.route("/francos/nuevo", methods=["POST"])
def francos_nuevo():
    if not _autenticado(): return _requiere_auth()
    legajo         = request.form.get("legajo", "").strip()
    nombre         = request.form.get("nombre", "").strip()
    tipo           = request.form.get("tipo", "RANGO").strip()
    estado         = request.form.get("estado", "Aprobado").strip()
    obs            = request.form.get("observaciones", "").strip()
    fecha_emision  = request.form.get("fecha_emision", "").strip()
    autorizado_por = request.form.get("autorizado_por", "").strip()
    ahora          = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not legajo or not nombre:
        return redirect(url_for("francos") + "?error=legajo_requerido")

    fechas_sueltas_lista = []
    if tipo == "UNICO":
        fecha_unica = request.form.get("fecha_unica", "").strip()
        if not fecha_unica:
            return redirect(url_for("francos") + "?error=fechas_requeridas")
        fecha_desde = fecha_unica
        fecha_hasta = fecha_unica
        dias = 1
        fechas_sueltas_json = "[]"
    elif tipo == "RANGO":
        fecha_desde = request.form.get("fecha_desde", "").strip()
        fecha_hasta = request.form.get("fecha_hasta", "").strip()
        if not fecha_desde or not fecha_hasta:
            return redirect(url_for("francos") + "?error=fechas_requeridas")
        dias = _dias_habiles(fecha_desde, fecha_hasta)
        if dias <= 0:
            return redirect(url_for("francos") + "?error=dias_cero")
        fechas_sueltas_json = "[]"
    else:
        fechas_raw = request.form.get("fechas_sueltas", "").strip()
        fechas_lista = [f.strip() for f in fechas_raw.replace(",", "\n").split("\n") if f.strip()]
        fechas_lista = [f for f in fechas_lista if _parse_fecha(f)]
        if not fechas_lista:
            return redirect(url_for("francos") + "?error=fechas_requeridas")
        fechas_sueltas_lista = fechas_lista
        dias = len(fechas_lista)
        fechas_sueltas_json = json.dumps(sorted(fechas_lista))
        fecha_desde = min(fechas_lista)
        fecha_hasta = max(fechas_lista)

    with _get_db() as conn:
        error_val = _validar_franco_nuevo(
            conn, legajo, tipo, fecha_desde, fecha_hasta, fechas_sueltas_lista
        )
        if error_val:
            return redirect(url_for("francos") + "?error=" + error_val)
        conn.execute(
            """INSERT INTO francos_tomados
               (legajo, nombre, tipo, fecha_desde, fecha_hasta, fechas_sueltas, dias, estado, observaciones, fecha_emision, autorizado_por, cargado_en)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (legajo, nombre, tipo, fecha_desde, fecha_hasta, fechas_sueltas_json, dias, estado, obs, fecha_emision, autorizado_por, ahora)
        )
        conn.commit()
    return redirect(url_for("francos"))

@app.route("/francos/eliminar/<int:fid>", methods=["POST"])
def francos_eliminar(fid):
    if not _autenticado(): return _requiere_auth()
    with _get_db() as conn:
        conn.execute("DELETE FROM francos_tomados WHERE id=?", (fid,))
        conn.commit()
    return redirect(url_for("francos"))

@app.route("/francos/aprobar/<int:fid>", methods=["POST"])
def francos_aprobar(fid):
    if not _autenticado(): return _requiere_auth()
    with _get_db() as conn:
        conn.execute("UPDATE francos_tomados SET estado='Aprobado' WHERE id=?", (fid,))
        conn.commit()
    return redirect(url_for("francos"))


@app.route("/francos/guardar-manual-semana", methods=["POST"])
def francos_guardar_manual_semana():
    if not _autenticado(): return jsonify({"error": "No autorizado"}), 401
    semana_num = int(request.form.get("semana_num", 0))
    mes        = request.form.get("mes", "").strip()
    if not semana_num or not mes:
        return jsonify({"error": "Semana y mes son requeridos"}), 400
    ahora = datetime.now().isoformat(timespec="seconds")
    guardados = 0
    with _get_db() as conn:
        emps = conn.execute(
            "SELECT legajo, nombre, departamento FROM empleados_extra WHERE activo=1"
        ).fetchall()
        for emp in emps:
            key = f"dias_{emp['legajo']}"
            val = request.form.get(key, "").strip()
            dias = int(val) if val.isdigit() else 0
            conn.execute("""
                INSERT INTO francos_semana_manual (legajo, nombre, departamento, semana_num, mes, dias, guardado_en)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(legajo, semana_num, mes) DO UPDATE SET dias=excluded.dias, guardado_en=excluded.guardado_en
            """, (emp["legajo"], emp["nombre"], emp["departamento"] or "", semana_num, mes, dias, ahora))
            guardados += 1
        conn.commit()
    return jsonify({"ok": True, "guardados": guardados})


# ═══════════════════════════════════════════════
# CONFIGURACION DE EMAIL
# ═══════════════════════════════════════════════
_EMAIL_CFG_FILE = Path("config_email.json")


def _leer_email_cfg():
    try:
        return json.loads(_EMAIL_CFG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _guardar_email_cfg(data):
    _EMAIL_CFG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@app.route("/configuracion/email", methods=["GET"])
def configuracion_email():
    if not _autenticado(): return _requiere_auth()
    cfg = _leer_email_cfg()
    with _get_db() as conn:
        supervisores = [dict(r) for r in conn.execute(
            "SELECT * FROM supervisores ORDER BY nombre"
        )]
    for s in supervisores:
        try:
            s["deptos_lista"] = json.loads(s["departamentos"])
        except Exception:
            s["deptos_lista"] = []
    departamentos = sorted({e["departamento"] for e in _empleados_conocidos() if e["departamento"]})
    return render_template("configuracion_email.html",
                           cfg=cfg,
                           supervisores=supervisores,
                           departamentos=departamentos)


@app.route("/configuracion/email/smtp", methods=["POST"])
def configuracion_email_smtp():
    if not _autenticado(): return _requiere_auth()
    cfg = _leer_email_cfg()
    cfg["smtp_user"]  = request.form.get("smtp_user",  "").strip()
    cfg["smtp_pass"]  = request.form.get("smtp_pass",  "").strip()
    cfg["smtp_host"]  = request.form.get("smtp_host",  "smtp.gmail.com").strip()
    cfg["smtp_port"]  = int(request.form.get("smtp_port", "587") or "587")
    cfg["smtp_from_name"] = request.form.get("smtp_from_name", "CM Horas Extras").strip()
    _guardar_email_cfg(cfg)
    return redirect(url_for("configuracion_email") + "?ok=smtp")


@app.route("/configuracion/supervisores/nuevo", methods=["POST"])
def supervisores_nuevo():
    if not _autenticado(): return _requiere_auth()
    nombre    = request.form.get("nombre", "").strip()
    email     = request.form.get("email",  "").strip()
    deptos    = request.form.getlist("departamentos")
    if not nombre or not email or not deptos:
        return redirect(url_for("configuracion_email") + "?error=sup_datos_requeridos")
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _get_db() as conn:
        conn.execute(
            "INSERT INTO supervisores (nombre, email, departamentos, cargado_en) VALUES (?,?,?,?)",
            (nombre, email, json.dumps(deptos), ahora)
        )
        conn.commit()
    return redirect(url_for("configuracion_email") + "?ok=supervisor")


@app.route("/configuracion/supervisores/eliminar/<int:sid>", methods=["POST"])
def supervisores_eliminar(sid):
    if not _autenticado(): return _requiere_auth()
    with _get_db() as conn:
        conn.execute("DELETE FROM supervisores WHERE id=?", (sid,))
        conn.commit()
    return redirect(url_for("configuracion_email"))


@app.route("/configuracion/supervisores/enviar/<int:sid>", methods=["POST"])
def supervisores_enviar(sid):
    if not _autenticado(): return _requiere_auth()
    import reporte_saldos_francos as rrf
    import traceback
    from datetime import datetime as _dt

    with _get_db() as conn:
        row = conn.execute("SELECT * FROM supervisores WHERE id=?", (sid,)).fetchone()
        sup = {k: row[k] for k in row.keys()} if row else None
    if not sup:
        return redirect(url_for("configuracion_email") + "?error=sin_datos")

    deptos = json.loads(sup["departamentos"])
    fecha_str  = _dt.now().strftime("%d/%m/%Y")
    fecha_arch = _dt.now().strftime("%Y%m%d")

    try:
        saldos = rrf._calcular_saldos()
    except Exception:
        app.logger.error("supervisores_enviar: _calcular_saldos\n" + traceback.format_exc())
        return redirect(url_for("configuracion_email") + "?error=sin_datos")

    por_depto = {}
    for s in saldos:
        por_depto.setdefault(s["departamento"], []).append(s)

    reportes_dir = Path(__file__).parent / "reportes"
    reportes_dir.mkdir(exist_ok=True)

    adjuntos = []
    for dep in deptos:
        emps = next((v for k, v in por_depto.items() if k.lower() == dep.lower()), None)
        if not emps:
            continue
        dep_limpio = dep.replace(" ", "_").replace("/", "-").upper()
        output_path = reportes_dir / f"reporte_francos_{dep_limpio}_{fecha_arch}.pdf"
        try:
            rrf._hacer_pdf(emps, dep.upper(), output_path, fecha_str)
            adjuntos.append(output_path)
        except Exception:
            app.logger.error(f"supervisores_enviar: _hacer_pdf {dep}\n" + traceback.format_exc())

    if not adjuntos:
        return redirect(url_for("configuracion_email") + "?error=sin_datos")

    cfg = rrf._leer_email_cfg()
    try:
        html_body = rrf._hacer_html_email(sup["nombre"], deptos, por_depto, fecha_str)
        rrf._enviar_email(cfg, sup["nombre"], sup["email"], adjuntos, html_body, fecha_str)
    except Exception:
        app.logger.error("supervisores_enviar: _enviar_email\n" + traceback.format_exc())
        return redirect(url_for("configuracion_email") + "?error=email")

    return redirect(url_for("configuracion_email") + f"?ok=reporte&sup_nombre={sup['nombre']}")


# ═══════════════════════════════════════════════
# EMPLEADOS EXTRA (depts sin fichadas automáticas)
# ═══════════════════════════════════════════════
_ODS_PERSONAL = Path(r"I:\Desde Facturacion\PERSONAL POR SECTOR.ods")


def _leer_ods_personal():
    """Parsea el ODS y devuelve lista de {nombre, departamento}."""
    try:
        import pandas as pd
        df = pd.read_excel(str(_ODS_PERSONAL), engine="odf", header=None)
    except Exception as exc:
        return [], str(exc)

    resultado = []
    depto_actual = ""
    for _, row in df.iterrows():
        val = str(row[0]).strip() if len(row) > 0 and not (hasattr(row[0], '__class__') and row[0].__class__.__name__ == 'float') else ""
        import math
        raw = row[0]
        if raw is None or (isinstance(raw, float) and math.isnan(raw)):
            continue
        val = str(raw).strip()
        if not val:
            continue
        # Heurística: nombre en mayúsculas sin coma y sin espacios intermedios de 1 palabra
        # → es encabezado de sección si no tiene dos palabras separadas por espacio (apellido nombre)
        palabras = val.split()
        if len(palabras) <= 2 and val == val.upper() and not any(c.isdigit() for c in val):
            # probablemente es nombre de sector
            depto_actual = val.title()
        else:
            if depto_actual:
                resultado.append({"nombre": val.upper(), "departamento": depto_actual.upper()})
    return resultado, None


@app.route("/empleados/importar")
def empleados_importar():
    if not _autenticado(): return _requiere_auth()
    with _get_db() as conn:
        existentes = {r["legajo"]: dict(r) for r in conn.execute(
            "SELECT * FROM empleados_extra WHERE activo=1"
        )}
    candidatos, error = _leer_ods_personal()
    # Solo mostramos sectores que no son los que ya están en sesion/periodos
    sectores_activos = {e["departamento"].upper() for e in _empleados_conocidos()}
    return render_template("empleados_importar.html",
                           candidatos=candidatos,
                           existentes=existentes,
                           error=error,
                           sectores_activos=sectores_activos)


@app.route("/empleados/importar/guardar", methods=["POST"])
def empleados_importar_guardar():
    if not _autenticado(): return _requiere_auth()
    nombres      = request.form.getlist("nombre")
    departamentos = request.form.getlist("departamento")
    legajos      = request.form.getlist("legajo")
    ahora        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    guardados    = 0
    with _get_db() as conn:
        for leg, nom, dep in zip(legajos, nombres, departamentos):
            leg = leg.strip()
            nom = nom.strip()
            dep = dep.strip()
            if not leg or not nom:
                continue
            conn.execute("""
                INSERT INTO empleados_extra (legajo, nombre, departamento, cargado_en)
                VALUES (?,?,?,?)
                ON CONFLICT(legajo) DO UPDATE
                SET nombre=excluded.nombre, departamento=excluded.departamento, activo=1
            """, (leg, nom, dep))
            guardados += 1
        conn.commit()
    return redirect(url_for("empleados_importar") + f"?ok={guardados}")


@app.route("/empleados/extra/eliminar/<legajo>", methods=["POST"])
def empleados_extra_eliminar(legajo):
    if not _autenticado(): return _requiere_auth()
    with _get_db() as conn:
        conn.execute("UPDATE empleados_extra SET activo=0 WHERE legajo=?", (legajo,))
        conn.commit()
    return redirect(url_for("empleados_importar"))


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
