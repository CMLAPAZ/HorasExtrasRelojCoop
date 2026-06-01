# -*- coding: utf-8 -*-
"""
reporte_saldos_francos.py
Genera un PDF de saldos de francos POR DEPARTAMENTO y lo envía
por email a los supervisores configurados.
Se ejecuta via Tarea Programada cada viernes a las 08:00.
"""

import json
import sqlite3
import os
import sys
import subprocess
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path

BASE_DIR     = Path(__file__).parent
DB_FILE      = BASE_DIR / "datos" / "cierres.db"
SESION_FILE  = BASE_DIR / "sesion.json"
REPORTES     = BASE_DIR / "reportes"
FONTS_DIR    = BASE_DIR / "recursos" / "fonts"
EMAIL_CFG    = BASE_DIR / "config_email.json"

FONT_REG  = FONTS_DIR / "DejaVuSans.ttf"
FONT_BOLD = FONTS_DIR / "DejaVuSans-Bold.ttf"
FONT_ITAL = FONTS_DIR / "DejaVuSans-Oblique.ttf"


# ──────────────────────────────────────────────────────
# Lectura de datos
# ──────────────────────────────────────────────────────

def _leer_sesion():
    try:
        return json.loads(SESION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _leer_email_cfg():
    try:
        return json.loads(EMAIL_CFG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_db():
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn


def _calcular_saldos():
    """
    Devuelve lista de dicts por empleado con saldo calculado.
    Combina: periodo_empleados (DB) + francos_generados (DB) + sesion.json.
    """
    sesion = _leer_sesion()

    iniciales_db        = {}
    gen_periodos        = {}
    gen_manual          = {}
    tomados_db          = {}
    detalle_tomados_db  = {}
    emps_db             = {}

    if DB_FILE.exists():
        with _get_db() as conn:
            for r in conn.execute("SELECT legajo, saldo FROM francos_saldo_inicial"):
                iniciales_db[str(r["legajo"])] = r["saldo"]
            for r in conn.execute(
                "SELECT pe.legajo, SUM(pe.francos) as total FROM periodo_empleados pe "
                "JOIN periodos p ON pe.periodo_id = p.id "
                "WHERE p.fecha_hasta > '2026-05-04' GROUP BY pe.legajo"
            ):
                gen_periodos[str(r["legajo"])] = r["total"] or 0
            for r in conn.execute(
                "SELECT legajo, SUM(dias) as total FROM francos_generados GROUP BY legajo"
            ):
                gen_manual[str(r["legajo"])] = r["total"] or 0
            for r in conn.execute(
                "SELECT legajo, SUM(dias) as total FROM francos_tomados GROUP BY legajo"
            ):
                tomados_db[str(r["legajo"])] = r["total"] or 0
            detalle_tomados_db = {}
            for r in conn.execute(
                "SELECT legajo, tipo, fecha_desde, fecha_hasta, fechas_sueltas, dias, estado, observaciones "
                "FROM francos_tomados ORDER BY fecha_desde, id"
            ):
                leg = str(r["legajo"])
                detalle_tomados_db.setdefault(leg, []).append({k: r[k] for k in r.keys()})
            for r in conn.execute(
                "SELECT DISTINCT legajo, nombre, departamento FROM periodo_empleados"
            ):
                emps_db[str(r["legajo"])] = {
                    "nombre":       r["nombre"],
                    "departamento": r["departamento"] or "Sin departamento",
                }
            # Empleados de francos_generados no presentes en periodo_empleados
            for r in conn.execute(
                "SELECT DISTINCT legajo, nombre, departamento FROM francos_generados"
            ):
                leg = str(r["legajo"])
                if leg not in emps_db:
                    emps_db[leg] = {
                        "nombre":       r["nombre"],
                        "departamento": r["departamento"] or "Sin departamento",
                    }
            # Empleados de empleados_extra (solo saldo inicial, sin fichadas)
            try:
                for r in conn.execute(
                    "SELECT DISTINCT legajo, nombre, departamento FROM empleados_extra"
                ):
                    leg = str(r["legajo"])
                    if leg not in emps_db:
                        emps_db[leg] = {
                            "nombre":       r["nombre"],
                            "departamento": r["departamento"] or "Sin departamento",
                        }
            except Exception:
                pass

    gen_sesion = {}
    emps_ses   = {}
    for d in sesion.values():
        leg = str(d.get("legajo", "")).strip()
        if not leg:
            continue
        emps_ses[leg] = {
            "nombre":       d.get("nombre", ""),
            "departamento": d.get("departamento", "") or "Sin departamento",
        }
        tot = d.get("totales") or {}
        gen_sesion[leg] = gen_sesion.get(leg, 0) + int(tot.get("francos", 0) or 0)

    todos = {**emps_db, **emps_ses}

    resultado = []
    for leg, info in todos.items():
        si  = iniciales_db.get(leg, 0)
        gen = gen_periodos.get(leg, 0) + gen_manual.get(leg, 0) + gen_sesion.get(leg, 0)
        tom = tomados_db.get(leg, 0)
        resultado.append({
            "legajo":           leg,
            "nombre":           info["nombre"],
            "departamento":     (info["departamento"] or "Sin departamento").upper(),
            "saldo_inicial":    si,
            "generados":        gen,
            "tomados":          tom,
            "saldo_actual":     si + gen - tom,
            "detalle_tomados":  detalle_tomados_db.get(leg, []),
        })

    resultado.sort(key=lambda e: (
        e["departamento"].lower(),
        int(e["legajo"]) if str(e["legajo"]).isdigit() else 0,
    ))
    return resultado


def _leer_supervisores():
    """Devuelve lista de {nombre, email, deptos_lista} desde la DB."""
    if not DB_FILE.exists():
        return []
    try:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT nombre, email, departamentos FROM supervisores WHERE activo=1"
            ).fetchall()
        result = []
        for r in rows:
            try:
                deptos = json.loads(r["departamentos"])
            except Exception:
                deptos = []
            result.append({"nombre": r["nombre"], "email": r["email"], "deptos": deptos})
        return result
    except Exception:
        return []


# ──────────────────────────────────────────────────────
# Helpers de fechas para detalle
# ──────────────────────────────────────────────────────

def _fmt_fecha(s):
    """'2025-03-10' -> '10/03/2025'."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return s or ""


def _desc_fecha_detalle(rec):
    tipo = (rec.get("tipo") or "").upper()
    if tipo == "SUELTAS":
        try:
            fechas = json.loads(rec.get("fechas_sueltas") or "[]")
            return ", ".join(_fmt_fecha(f) for f in sorted(fechas))
        except Exception:
            return ""
    fd = _fmt_fecha(rec.get("fecha_desde", ""))
    fh = _fmt_fecha(rec.get("fecha_hasta", ""))
    if fh and fh != fd:
        return f"{fd} → {fh}"
    return fd


# ──────────────────────────────────────────────────────
# Generacion del PDF
# ──────────────────────────────────────────────────────

def _hacer_pdf(emps, departamento, output_path, fecha_str):
    from fpdf import FPDF

    class PDF(FPDF):
        def __init__(self):
            super().__init__(orientation="L", unit="mm", format="A4")
            self.set_auto_page_break(auto=True, margin=15)
            self._unicode = False
            if (os.path.exists(str(FONT_REG)) and os.path.exists(str(FONT_BOLD))
                    and os.path.exists(str(FONT_ITAL))):
                try:
                    self.add_font("DejaVu", "",  str(FONT_REG),  uni=True)
                    self.add_font("DejaVu", "B", str(FONT_BOLD), uni=True)
                    self.add_font("DejaVu", "I", str(FONT_ITAL), uni=True)
                    self._unicode = True
                except Exception:
                    pass

        def _fam(self):
            return "DejaVu" if self._unicode else "Helvetica"

        def header(self):
            fam = self._fam()
            self.set_font(fam, "B", 13)
            self.cell(0, 10,
                      f"Saldos de Francos — {departamento.upper()}    ({fecha_str})",
                      ln=1, align="C")
            self.ln(2)

        def footer(self):
            fam = self._fam()
            self.set_y(-13)
            self.set_font(fam, "I", 7)
            self.cell(0, 8, f"Pag. {self.page_no()}", 0, 0, "L")
            self.set_x(-80)
            self.cell(75, 8, "CM_HorasExtras — Generado automaticamente", 0, 0, "R")

    pdf = PDF()
    pdf.add_page()
    fam = pdf._fam()

    COLS   = ["Leg.", "Nombre",  "Saldo Inicial", "Generados", "Tomados", "Saldo Actual"]
    ANCHOS = [15,     100,       35,               30,          25,        35]

    def _encabezado_cols():
        pdf.set_fill_color(200, 215, 240)
        pdf.set_font(fam, "B", 8)
        for col, ancho in zip(COLS, ANCHOS):
            pdf.cell(ancho, 6, col, 1, 0, "C", fill=True)
        pdf.ln()

    _encabezado_cols()

    for i, emp in enumerate(emps):
        if pdf.get_y() + 7 > pdf.h - pdf.b_margin:
            pdf.add_page()
            _encabezado_cols()

        relleno = i % 2 == 0
        if relleno:
            pdf.set_fill_color(240, 245, 255)
        else:
            pdf.set_fill_color(255, 255, 255)

        pdf.set_font(fam, "", 8)
        pdf.set_text_color(0, 0, 0)

        pdf.cell(ANCHOS[0], 6, str(emp["legajo"]),       1, 0, "C", relleno)
        pdf.cell(ANCHOS[1], 6, emp["nombre"],             1, 0, "L", relleno)
        pdf.cell(ANCHOS[2], 6, str(emp["saldo_inicial"]), 1, 0, "C", relleno)
        pdf.cell(ANCHOS[3], 6, str(emp["generados"]),     1, 0, "C", relleno)
        pdf.cell(ANCHOS[4], 6, str(emp["tomados"]),       1, 0, "C", relleno)

        saldo = emp["saldo_actual"]
        if saldo < 0:
            pdf.set_text_color(180, 0, 0)
        elif saldo > 0:
            pdf.set_text_color(0, 130, 0)
        else:
            pdf.set_text_color(100, 100, 100)
        pdf.cell(ANCHOS[5], 6, str(saldo), 1, 0, "C", relleno)
        pdf.set_text_color(0, 0, 0)
        pdf.ln()

        # Sub-filas de detalle francos tomados
        for det in emp.get("detalle_tomados", []):
            if pdf.get_y() + 5 > pdf.h - pdf.b_margin:
                pdf.add_page()
                _encabezado_cols()
            pdf.set_font(fam, "I", 7)
            pdf.set_text_color(80, 80, 80)
            pdf.set_fill_color(248, 248, 252)
            fecha_txt  = _desc_fecha_detalle(det)
            estado_txt = (det.get("estado") or "").capitalize()
            obs_txt    = (det.get("observaciones") or "").strip()
            detalle_txt = f"  {fecha_txt}   {estado_txt}"
            if obs_txt:
                detalle_txt += f"   ({obs_txt})"
            dias_det = str(det.get("dias", ""))
            pdf.cell(ANCHOS[0], 5, "", "LB", 0, "C", fill=True)
            pdf.cell(ANCHOS[1] + ANCHOS[2] + ANCHOS[3], 5, detalle_txt, "LB", 0, "L", fill=True)
            pdf.cell(ANCHOS[4], 5, dias_det, "LRB", 0, "C", fill=True)
            pdf.cell(ANCHOS[5], 5, "", "RB", 0, "C", fill=True)
            pdf.set_text_color(0, 0, 0)
            pdf.ln()

    pdf.output(str(output_path))


# ──────────────────────────────────────────────────────
# Email HTML
# ──────────────────────────────────────────────────────

def _saldo_color(v):
    if v > 0:  return "color:#166534;font-weight:bold"
    if v < 0:  return "color:#b91c1c;font-weight:bold"
    return "color:#64748b"


def _hacer_html_email(sup_nombre, deptos, por_depto, fecha_str):
    """Genera cuerpo HTML del email con tabla de saldos por departamento."""
    tablas_html = ""
    for dep in deptos:
        emps = None
        for k, v in por_depto.items():
            if k.lower() == dep.lower():
                emps = v
                break
        if not emps:
            continue
        t_ini = sum(e["saldo_inicial"] for e in emps)
        t_gen = sum(e["generados"]     for e in emps)
        t_tom = sum(e["tomados"]       for e in emps)
        t_act = sum(e["saldo_actual"]  for e in emps)

        filas = ""
        for e in emps:
            sa = e["saldo_actual"]
            filas += (
                f"<tr>"
                f"<td>{e['legajo']}</td>"
                f"<td>{e['nombre']}</td>"
                f"<td style='text-align:center'>{e['saldo_inicial']}</td>"
                f"<td style='text-align:center;color:#854d0e;font-weight:bold'>+{e['generados']}</td>"
                f"<td style='text-align:center;color:#b91c1c;font-weight:bold'>-{e['tomados']}</td>"
                f"<td style='text-align:center;{_saldo_color(sa)}'>{sa}</td>"
                f"</tr>"
            )
            for det in e.get("detalle_tomados", []):
                fecha_txt  = _desc_fecha_detalle(det)
                estado_txt = (det.get("estado") or "").capitalize()
                obs_txt    = (det.get("observaciones") or "").strip()
                obs_part   = f" &mdash; {obs_txt}" if obs_txt else ""
                filas += (
                    f"<tr style='background:#f8f8fc;font-size:.78rem;color:#64748b'>"
                    f"<td></td>"
                    f"<td colspan='3' style='padding-left:18px;font-style:italic'>"
                    f"{fecha_txt} &nbsp; <span style='color:#b91c1c'>{estado_txt}</span>{obs_part}"
                    f"</td>"
                    f"<td style='text-align:center;color:#b91c1c'>{det.get('dias','')}</td>"
                    f"<td></td>"
                    f"</tr>"
                )
        filas += (
            f"<tr style='background:#eef2ff;font-weight:bold;border-top:2px solid #c7d4f0'>"
            f"<td colspan='2' style='text-align:right;color:#64748b'>Subtotal</td>"
            f"<td style='text-align:center'>{t_ini}</td>"
            f"<td style='text-align:center;color:#854d0e'>+{t_gen}</td>"
            f"<td style='text-align:center;color:#b91c1c'>-{t_tom}</td>"
            f"<td style='text-align:center;{_saldo_color(t_act)}'>{t_act}</td>"
            f"</tr>"
        )

        tablas_html += f"""
<h3 style='color:#1e3a5f;font-size:.95rem;margin:22px 0 8px;
           border-bottom:2px solid #dbeafe;padding-bottom:4px'>
  {dep.upper()} &nbsp;<span style='font-size:.8rem;font-weight:normal;color:#64748b'>
  ({len(emps)} empleados)</span>
</h3>
<table style='width:100%;border-collapse:collapse;font-size:.84rem;margin-bottom:16px'>
  <thead>
    <tr style='background:#1e3a5f;color:#fff'>
      <th style='padding:7px 10px;text-align:left'>Legajo</th>
      <th style='padding:7px 10px;text-align:left'>Nombre</th>
      <th style='padding:7px 10px;text-align:center'>Saldo Ini.</th>
      <th style='padding:7px 10px;text-align:center'>Gen.</th>
      <th style='padding:7px 10px;text-align:center'>Tom.</th>
      <th style='padding:7px 10px;text-align:center'>Saldo Actual</th>
    </tr>
  </thead>
  <tbody style='font-size:.83rem'>
    {filas}
  </tbody>
</table>"""

    if not tablas_html:
        tablas_html = "<p style='color:#64748b'>Sin datos para los departamentos asignados.</p>"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset='UTF-8'></head>
<body style='font-family:Arial,sans-serif;color:#111827;max-width:720px;margin:0 auto;padding:24px'>
  <h2 style='color:#0f172a;font-size:1.15rem;margin-bottom:4px'>
    CM Horas Extras &mdash; Saldos de Francos
  </h2>
  <p style='color:#64748b;font-size:.88rem;margin-bottom:20px'>
    Estimado/a <strong>{sup_nombre}</strong>,
    se adjuntan los informes de saldos al <strong>{fecha_str}</strong>.
  </p>
  {tablas_html}
  <p style='margin-top:28px;font-size:.75rem;color:#94a3b8;
            border-top:1px solid #e5e7eb;padding-top:10px'>
    CM_HorasExtras &mdash; Generado automáticamente el {fecha_str}
  </p>
</body>
</html>"""


# ──────────────────────────────────────────────────────
# Envio de email
# ──────────────────────────────────────────────────────

def _enviar_email(cfg, destinatario_nombre, destinatario_email, adjuntos, html_body, fecha_str):
    """
    Envía un email con cuerpo HTML y PDFs adjuntos (Gmail / cualquier SMTP).
    adjuntos: lista de Path
    """
    smtp_user      = cfg.get("smtp_user", "")
    smtp_pass      = cfg.get("smtp_pass", "")
    smtp_host      = cfg.get("smtp_host", "smtp.gmail.com")
    smtp_port      = int(cfg.get("smtp_port", 587))
    smtp_from_name = cfg.get("smtp_from_name", "CM Horas Extras")

    msg = MIMEMultipart("mixed")
    msg["From"]    = f"{smtp_from_name} <{smtp_user}>"
    msg["To"]      = f"{destinatario_nombre} <{destinatario_email}>"
    msg["Subject"] = f"Saldos de Francos — {fecha_str}"

    body_alt = MIMEMultipart("alternative")
    plain = (
        f"Estimado/a {destinatario_nombre},\n\n"
        f"Se adjuntan los informes de saldos de francos al {fecha_str}.\n\n"
        f"— CM Horas Extras (generado automáticamente)"
    )
    body_alt.attach(MIMEText(plain,     "plain", "utf-8"))
    body_alt.attach(MIMEText(html_body, "html",  "utf-8"))
    msg.attach(body_alt)

    for pdf_path in adjuntos:
        with open(pdf_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{pdf_path.name}"',
        )
        msg.attach(part)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [destinatario_email], msg.as_bytes())


# ──────────────────────────────────────────────────────
# Guardar parciales de francos en DB
# ──────────────────────────────────────────────────────

def _guardar_francos_parciales(sesion):
    """Snapshot semanal: guarda francos del sesion activo en francos_semana_parcial."""
    if not DB_FILE.exists() or not sesion:
        return
    ahora = datetime.now().isoformat(timespec="seconds")
    por_semana = {}
    for d in sesion.values():
        leg = str(d.get("legajo", "")).strip()
        if not leg:
            continue
        sem = d.get("semana", 0)
        por_semana.setdefault(sem, []).append(d)
    try:
        with _get_db() as conn:
            for sem, tokens in por_semana.items():
                conn.execute("DELETE FROM francos_semana_parcial WHERE semana_num=?", (sem,))
                for d in tokens:
                    dias = int((d.get("totales") or {}).get("francos", 0) or 0)
                    conn.execute(
                        "INSERT INTO francos_semana_parcial (legajo, nombre, departamento, semana_num, dias, guardado_en) VALUES (?,?,?,?,?,?)",
                        (str(d.get("legajo","")), d.get("nombre",""), d.get("departamento",""), sem, dias, ahora)
                    )
            conn.commit()
    except Exception:
        pass


# ──────────────────────────────────────────────────────
# Notificacion Windows
# ──────────────────────────────────────────────────────

def _notificar(mensaje, titulo="Reporte Francos"):
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Information; "
        "$n.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info; "
        f"$n.BalloonTipTitle = '{titulo}'; "
        f"$n.BalloonTipText = '{mensaje}'; "
        "$n.Visible = $true; "
        "$n.ShowBalloonTip(8000); "
        "Start-Sleep -Seconds 9; "
        "$n.Dispose()"
    )
    try:
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


# ──────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────

def main():
    REPORTES.mkdir(exist_ok=True)

    if not DB_FILE.exists() and not SESION_FILE.exists():
        _notificar("No se encontraron datos.", "Error - Reporte Francos")
        sys.exit(1)

    fecha_str  = datetime.now().strftime("%d/%m/%Y")
    fecha_arch = datetime.now().strftime("%Y%m%d")

    sesion = _leer_sesion()
    _guardar_francos_parciales(sesion)

    try:
        saldos = _calcular_saldos()
    except Exception as exc:
        _notificar(f"Error leyendo datos:\n{exc}", "Error - Reporte Francos")
        sys.exit(1)

    if not saldos:
        _notificar("No hay datos de empleados.", "Reporte Francos")
        sys.exit(0)

    # Agrupar por departamento (clave original para PDF, clave lower para lookup)
    por_depto  = {}
    for s in saldos:
        por_depto.setdefault(s["departamento"], []).append(s)

    pdfs_por_depto = {}   # depto_lower -> Path
    errores_gen    = []

    for dep, emps in sorted(por_depto.items()):
        dep_limpio  = dep.replace(" ", "_").replace("/", "-")
        nombre_pdf  = f"reporte_francos_{dep_limpio}_{fecha_arch}.pdf"
        output_path = REPORTES / nombre_pdf
        try:
            _hacer_pdf(emps, dep, output_path, fecha_str)
            pdfs_por_depto[dep.lower()] = output_path
        except Exception as exc:
            errores_gen.append(f"{dep}: {exc}")

    # Enviar emails a supervisores
    cfg          = _leer_email_cfg()
    supervisores = _leer_supervisores()
    errores_mail = []
    enviados     = 0

    if cfg.get("smtp_user") and cfg.get("smtp_pass") and supervisores:
        for sup in supervisores:
            adjuntos = []
            for dep in sup["deptos"]:
                pdf = pdfs_por_depto.get(dep.lower())
                if pdf and pdf.exists():
                    adjuntos.append(pdf)
            if not adjuntos:
                continue
            try:
                html_body = _hacer_html_email(sup["nombre"], sup["deptos"], por_depto, fecha_str)
                _enviar_email(cfg, sup["nombre"], sup["email"], adjuntos, html_body, fecha_str)
                enviados += 1
            except Exception as exc:
                errores_mail.append(f"{sup['email']}: {exc}")

    # Notificación final
    partes = []
    if pdfs_por_depto:
        partes.append(f"{len(pdfs_por_depto)} reporte(s) en reportes/")
    if enviados:
        partes.append(f"enviado a {enviados} supervisor(es)")
    if errores_gen:
        partes.append(f"{len(errores_gen)} error(es) de generacion")
    if errores_mail:
        partes.append(f"{len(errores_mail)} error(es) de envio")

    titulo = "Saldos de Francos — Viernes" if not errores_mail and not errores_gen else "Francos — con advertencias"
    _notificar(" | ".join(partes) if partes else "Completado", titulo)


if __name__ == "__main__":
    main()
