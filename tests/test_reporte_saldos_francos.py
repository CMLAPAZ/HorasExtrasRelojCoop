# -*- coding: utf-8 -*-
"""
reporte_saldos_francos.py — proceso INDEPENDIENTE de servidor.py (corre
vía tarea programada en PythonAnywhere) con su propia _calcular_saldos().

Cubre:
- _calcular_saldos() agrupa por nombre_visible() del módulo compartido
  departamentos.py, así un mismo depto cargado con o sin tilde en
  distintas fuentes queda en un único grupo (3-7).
- _agrupar_supervisores_por_email(): un supervisor configurado con
  "Administración" (con tilde) o "administracion" (sin tilde) encuentra
  el mismo PDF generado (3-4); Redes en un único grupo (5); sin regresión
  en Guardias/Internet/Telefonía (6).
- Deduplicación de envíos: dos responsables con la misma dirección de
  email reciben un único correo con todos sus informes; direcciones
  distintas siguen recibiendo envíos separados.
"""
import json
import sqlite3

import pytest

import servidor
import reporte_saldos_francos as rep


@pytest.fixture
def db_temporal(tmp_path, monkeypatch):
    db_file = tmp_path / "cierres_test.db"
    monkeypatch.setattr(servidor, "DATOS_DIR", tmp_path)
    monkeypatch.setattr(servidor, "DB_FILE", db_file)
    servidor._init_db()

    monkeypatch.setattr(rep, "DB_FILE", db_file)
    # _calcular_saldos() lee SESION_FILE; apuntar a un archivo inexistente
    # para no mezclar con sesion.json real del proyecto.
    monkeypatch.setattr(rep, "SESION_FILE", tmp_path / "sesion_inexistente.json")
    return db_file


def _insert_periodo_empleado(db_file, legajo, nombre, departamento):
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id, legajo, nombre, departamento) VALUES (1,?,?,?)",
        (legajo, nombre, departamento),
    )
    conn.commit()
    conn.close()


def _insert_supervisor(db_file, nombre, email, deptos):
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "INSERT INTO supervisores (nombre, email, departamentos, activo) VALUES (?,?,?,1)",
        (nombre, email, json.dumps(deptos)),
    )
    conn.commit()
    conn.close()


def _por_depto(saldos):
    grupos = {}
    for s in saldos:
        grupos.setdefault(s["departamento"], []).append(s)
    return grupos


# ──────────────────────────────────────────────────────────────
# 3. _calcular_saldos normaliza "administracion"/"Administración" -> un grupo
# ──────────────────────────────────────────────────────────────

def test_calcular_saldos_unifica_administracion_con_y_sin_tilde(db_temporal):
    _insert_periodo_empleado(db_temporal, "10", "PEREZ", "administracion")   # fuente vieja, sin tilde
    _insert_periodo_empleado(db_temporal, "11", "GOMEZ", "Administración")   # fuente nueva, con tilde

    saldos = rep._calcular_saldos()
    deptos = {s["legajo"]: s["departamento"] for s in saldos}

    assert deptos["10"] == "Administración"
    assert deptos["11"] == "Administración"

    grupos = _por_depto(saldos)
    assert set(grupos.keys()) == {"Administración"}
    assert len(grupos["Administración"]) == 2


# ──────────────────────────────────────────────────────────────
# 3-4. Supervisor configurado con o sin tilde encuentra el mismo PDF
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("dep_supervisor", ["Administración", "administracion", "ADMINISTRACION", "admin"])
def test_supervisor_administracion_encuentra_pdf_con_o_sin_tilde(db_temporal, dep_supervisor):
    _insert_periodo_empleado(db_temporal, "10", "PEREZ", "administracion")

    saldos = rep._calcular_saldos()
    grupos = _por_depto(saldos)

    # Misma lógica de pdfs_por_depto que main(): clave_canonica(dep) -> pdf
    pdfs_por_depto = {rep.clave_canonica(dep): f"reporte_{dep}.pdf" for dep in grupos}

    pdf = pdfs_por_depto.get(rep.clave_canonica(dep_supervisor))
    assert pdf is not None, f"Supervisor con depto={dep_supervisor!r} no encontró el PDF de Administración"


# ──────────────────────────────────────────────────────────────
# 5. Redes en un único grupo (fuentes mixtas redes/Redes)
# ──────────────────────────────────────────────────────────────

def test_redes_unico_grupo_en_reporte(db_temporal):
    _insert_periodo_empleado(db_temporal, "133", "ZABALA ANTONIO", "Redes")
    _insert_periodo_empleado(db_temporal, "1", "OTRO EMPLEADO", "redes")

    saldos = rep._calcular_saldos()
    grupos = _por_depto(saldos)

    assert set(grupos.keys()) == {"Redes"}
    assert len(grupos["Redes"]) == 2


# ──────────────────────────────────────────────────────────────
# 6. Sin regresión: Guardias / Internet / Telefonía
# ──────────────────────────────────────────────────────────────

def test_sin_regresion_guardias_internet_telefonia(db_temporal):
    _insert_periodo_empleado(db_temporal, "113", "MAYDANA", "GUARDIAS")
    _insert_periodo_empleado(db_temporal, "50", "GOMEZ NESTOR", "internet")
    _insert_periodo_empleado(db_temporal, "16", "BAROLIN FRANCA", "Telefonia")  # sin tilde

    saldos = rep._calcular_saldos()
    deptos = {s["legajo"]: s["departamento"] for s in saldos}

    assert deptos["113"] == "Guardias"
    assert deptos["50"] == "Internet"
    assert deptos["16"] == "Telefonía"


# ──────────────────────────────────────────────────────────────
# Deduplicación de envíos por email — _agrupar_supervisores_por_email
# ──────────────────────────────────────────────────────────────

def test_agrupar_supervisores_mismo_email_un_solo_envio():
    supervisores = [
        {"nombre": "Ing. Gatti", "email": "gatti@celp.com.ar", "deptos": ["Redes"]},
        {"nombre": "Otro Responsable", "email": " Gatti@CELP.com.ar ", "deptos": ["Administración"]},
    ]
    agrupados = rep._agrupar_supervisores_por_email(supervisores)

    assert len(agrupados) == 1
    assert agrupados[0]["email"] == "gatti@celp.com.ar"


def test_agrupar_supervisores_envio_unico_incluye_todos_los_deptos():
    supervisores = [
        {"nombre": "Ing. Gatti", "email": "gatti@celp.com.ar", "deptos": ["Redes"]},
        {"nombre": "Otro Responsable", "email": "gatti@celp.com.ar", "deptos": ["Administración", "Redes"]},
    ]
    agrupados = rep._agrupar_supervisores_por_email(supervisores)

    assert len(agrupados) == 1
    assert set(agrupados[0]["deptos"]) == {"Redes", "Administración"}
    assert agrupados[0]["deptos"].count("Redes") == 1  # no duplica deptos repetidos


def test_agrupar_supervisores_mismo_email_administracion_con_y_sin_tilde_un_solo_depto():
    """Administración y administracion son el mismo departamento (clave_canonica):
    deben colapsar a una única entrada, almacenada con su nombre_visible()."""
    supervisores = [
        {"nombre": "Ing. Gatti", "email": "gatti@celp.com.ar", "deptos": ["Administración"]},
        {"nombre": "Otro Responsable", "email": "gatti@celp.com.ar", "deptos": ["administracion"]},
    ]
    agrupados = rep._agrupar_supervisores_por_email(supervisores)

    assert len(agrupados) == 1
    assert agrupados[0]["deptos"] == ["Administración"]


def test_agrupar_supervisores_un_mismo_depto_repetido_no_duplica():
    """Un mismo departamento mencionado varias veces (con distinta grafía)
    nunca aparece más de una vez en el grupo."""
    supervisores = [
        {"nombre": "Ing. Gatti", "email": "gatti@celp.com.ar",
         "deptos": ["Redes", "redes", "REDES", "Administración", "administracion"]},
    ]
    agrupados = rep._agrupar_supervisores_por_email(supervisores)

    assert len(agrupados) == 1
    assert agrupados[0]["deptos"] == ["Redes", "Administración"]


def test_agrupar_supervisores_emails_distintos_quedan_separados():
    supervisores = [
        {"nombre": "Ing. Gatti", "email": "gatti@celp.com.ar", "deptos": ["Redes"]},
        {"nombre": "Otro Responsable", "email": "otro@celp.com.ar", "deptos": ["Administración"]},
    ]
    agrupados = rep._agrupar_supervisores_por_email(supervisores)

    assert len(agrupados) == 2
    assert {g["email"] for g in agrupados} == {"gatti@celp.com.ar", "otro@celp.com.ar"}


# ──────────────────────────────────────────────────────────────
# main(): un único correo a la dirección compartida, con todos los PDFs
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def main_io(tmp_path, monkeypatch):
    """Aisla main() de filesystem/SMTP reales: REPORTES, EMAIL_CFG,
    NO_ENVIAR_FILE en tmp_path; _enviar_email y _notificar mockeados."""
    reportes_dir = tmp_path / "reportes"
    email_cfg = tmp_path / "config_email.json"
    email_cfg.write_text(json.dumps({
        "smtp_host": "smtp.example.com", "smtp_port": 587,
        "smtp_user": "bot@celp.com.ar", "smtp_pass": "x",
        "smtp_from_name": "CM Horas Extras",
    }), encoding="utf-8")

    monkeypatch.setattr(rep, "REPORTES", reportes_dir)
    monkeypatch.setattr(rep, "EMAIL_CFG", email_cfg)
    monkeypatch.setattr(rep, "NO_ENVIAR_FILE", tmp_path / "no_enviar_inexistente.json")

    enviados = []
    monkeypatch.setattr(
        rep, "_enviar_email",
        lambda cfg, nombre, email, adjuntos, html_body, fecha_str: enviados.append({
            "nombre": nombre, "email": email, "adjuntos": list(adjuntos), "html_body": html_body,
        })
    )
    monkeypatch.setattr(rep, "_notificar", lambda *a, **k: None)
    return enviados


def test_main_un_solo_correo_a_email_compartido(db_temporal, main_io):
    _insert_periodo_empleado(db_temporal, "133", "ZABALA ANTONIO", "Redes")
    _insert_periodo_empleado(db_temporal, "10", "PEREZ", "Administración")
    _insert_supervisor(db_temporal, "Ing. Gatti", "gatti@celp.com.ar", ["Redes"])
    _insert_supervisor(db_temporal, "Otro Responsable", " Gatti@CELP.com.ar ", ["Administración"])

    rep.main()

    assert len(main_io) == 1
    envio = main_io[0]
    assert envio["email"] == "gatti@celp.com.ar"
    assert len(envio["adjuntos"]) == 2  # informes de Redes y Administración, ninguno se pierde
    assert envio["adjuntos"][0] != envio["adjuntos"][1]  # dos adjuntos diferentes
    assert envio["html_body"].count("<h3") == 2  # una sección por departamento


def test_main_emails_distintos_generan_envios_separados(db_temporal, main_io):
    _insert_periodo_empleado(db_temporal, "133", "ZABALA ANTONIO", "Redes")
    _insert_periodo_empleado(db_temporal, "10", "PEREZ", "Administración")
    _insert_supervisor(db_temporal, "Ing. Gatti", "gatti@celp.com.ar", ["Redes"])
    _insert_supervisor(db_temporal, "Otro Responsable", "otro@celp.com.ar", ["Administración"])

    rep.main()

    assert len(main_io) == 2
    emails = {e["email"] for e in main_io}
    assert emails == {"gatti@celp.com.ar", "otro@celp.com.ar"}
    for e in main_io:
        assert len(e["adjuntos"]) == 1


def test_main_mismo_email_administracion_con_y_sin_tilde_un_solo_pdf(db_temporal, main_io):
    """Dos supervisores con el mismo email, uno configurado con
    'Administración' y el otro con 'administracion': se considera un único
    departamento -> una sola sección en el HTML y un solo PDF adjunto
    (no se duplica)."""
    _insert_periodo_empleado(db_temporal, "10", "PEREZ", "Administración")
    _insert_supervisor(db_temporal, "Ing. Gatti", "gatti@celp.com.ar", ["Administración"])
    _insert_supervisor(db_temporal, "Otro Responsable", "gatti@celp.com.ar", ["administracion"])

    rep.main()

    assert len(main_io) == 1
    envio = main_io[0]
    assert len(envio["adjuntos"]) == 1
    assert envio["html_body"].count("<h3") == 1


def test_main_mismo_depto_repetido_no_duplica_adjunto(db_temporal, main_io):
    """Un mismo departamento mencionado más de una vez (con distinta grafía)
    para el mismo email nunca duplica el PDF adjunto."""
    _insert_periodo_empleado(db_temporal, "133", "ZABALA ANTONIO", "Redes")
    _insert_supervisor(db_temporal, "Ing. Gatti", "gatti@celp.com.ar", ["Redes"])
    _insert_supervisor(db_temporal, "Otro Responsable", "gatti@celp.com.ar", ["redes", "REDES"])

    rep.main()

    assert len(main_io) == 1
    assert len(main_io[0]["adjuntos"]) == 1
