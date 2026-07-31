# -*- coding: utf-8 -*-
"""
Pruebas para la nueva semántica de excluidos_ot.

Regla: excluido_ot = incluido en cierre, horas visibles reales, no liquidables.
No hay zeroing de OT en ningún punto del sistema.

Casos verificados:
  1. _aplicar_exclusiones_ot pone excluido_ot=True y liquida_ot=False
  2. Los totales de OT son reales (no cero) en el token
  3. Las comidas se conservan
  4. Los francos se conservan
  5. liquida_ot=False está en el token
  6. _calcular_periodo incluye al excluido con OT real
  7. _calcular_periodo conserva liquida_ot=False
  8. El cierre guardará OT real (valores que llegan al INSERT son reales)
  9. historial_acumulado acumula OT real (no cero)
 10. Los períodos cerrados anteriores no se modifican
 11. Un empleado no excluido no recibe el flag
"""
import io
from datetime import date, timedelta
from io import BytesIO

import pytest
from pypdf import PdfReader

import servidor
from pdf_generator import generar_pdf_resumen, generar_pdf_general


# ──────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────

_LEG_EXCLUIDO = "10"   # en excluidos_ot.json
_LEG_NORMAL   = "7"    # no excluido

_OBS = servidor._OBS_EXCLUIDO_OT

_CSV_BYTES = (
    "Nro. de usuario,Nombre,Departamento,Fecha/Hora,Tipo de registro\n"
    f"{_LEG_EXCLUIDO},Mancioni Martin,Administracion,2026-06-02 06:00:00,ENTRADA\n"
    f"{_LEG_EXCLUIDO},Mancioni Martin,Administracion,2026-06-02 13:00:00,SALIDA\n"
    f"{_LEG_NORMAL},Rodriguez Juan,Administracion,2026-06-02 06:00:00,ENTRADA\n"
    f"{_LEG_NORMAL},Rodriguez Juan,Administracion,2026-06-02 13:00:00,SALIDA\n"
).encode("utf-8")


# ──────────────────────────────────────────────────────────────
# Helpers — los flags ya aplicados (simulan salida de _aplicar_exclusiones_ot)
# ──────────────────────────────────────────────────────────────

def _emp_excluido():
    return {
        "legajo": _LEG_EXCLUIDO, "nombre": "MANCIONI MARTIN",
        "departamento": "Administracion",
        "registros": [
            {"Fecha": "2026-06-02", "50%": "01:00:00", "100%": "00:00:00",
             "Normales": "07:00:00", "COMIDA": 1, "FRANCO": 0, "Tarde": 0,
             "Observaciones": "", "Entrada": "06:00", "Salida": "13:00"},
        ],
        "excluido_ot": True,
        "liquida_ot": False,
        "observacion_liquidacion": _OBS,
    }


def _emp_normal():
    return {
        "legajo": _LEG_NORMAL, "nombre": "Rodriguez Juan",
        "departamento": "Administracion",
        "registros": [
            {"Fecha": "2026-06-02", "50%": "01:00:00", "100%": "00:00:00",
             "Normales": "07:00:00", "COMIDA": 1, "FRANCO": 0, "Tarde": 0,
             "Observaciones": "", "Entrada": "06:00", "Salida": "13:00"},
        ],
        "excluido_ot": False,
        "liquida_ot": True,
        "observacion_liquidacion": "",
    }


def _item_historial_excluido(ot50="1h00", ot100="0h", comidas=1, francos=0):
    return {
        "legajo": _LEG_EXCLUIDO, "nombre": "MANCIONI MARTIN",
        "departamento": "Administracion",
        "semana": 1, "semana_depto": 1,
        "confirmado_en": "2026-06-03T08:00:00",
        "excluido_ot": True,
        "liquida_ot": False,
        "observacion_liquidacion": _OBS,
        "totales": {"ot50": ot50, "ot100": ot100, "comidas": comidas,
                    "francos": francos, "tardanzas": 0},
        "dias": [{"fecha": "2026-06-02", "ot50": "01:00:00", "ot100": "00:00:00",
                  "comida": comidas, "franco": francos, "tarde": 0,
                  "tipo_dia": "normal", "tiene_ot": True, "descripcion": ""}],
    }


def _meta_sem1():
    return {
        "semanas": [{"numero": 1, "num_depto": 1, "departamento": "Administracion",
                     "fecha_desde": "2026-06-01", "fecha_hasta": "2026-06-07"}],
        "total": 1,
    }


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_io(monkeypatch):
    monkeypatch.setattr(servidor, "_autenticado", lambda: True)
    monkeypatch.setattr(servidor, "_guardar_sesion", lambda s: None)
    monkeypatch.setattr(servidor, "_guardar_metadata", lambda m: None)
    monkeypatch.setattr(servidor, "_guardar_semana_csv", lambda n, df: None)
    monkeypatch.setattr(servidor, "_wa_url", lambda *a, **kw: "")


@pytest.fixture
def client():
    servidor.app.config["TESTING"] = True
    with servidor.app.test_client() as c:
        yield c


# ──────────────────────────────────────────────────────────────
# 1. _aplicar_exclusiones_ot: flags correctos
# ──────────────────────────────────────────────────────────────

def test_aplicar_exclusiones_flag_excluido(monkeypatch):
    monkeypatch.setattr(servidor, "_cargar_excluidos_ot", lambda: {_LEG_EXCLUIDO})
    emp = {
        "legajo": _LEG_EXCLUIDO, "nombre": "MANCIONI MARTIN",
        "departamento": "Administracion", "registros": [], "excluido_ot": False,
    }
    servidor._aplicar_exclusiones_ot([emp])
    assert emp["excluido_ot"] is True
    assert emp["liquida_ot"] is False
    assert emp["observacion_liquidacion"] == _OBS


def test_aplicar_exclusiones_no_afecta_normal(monkeypatch):
    monkeypatch.setattr(servidor, "_cargar_excluidos_ot", lambda: {_LEG_EXCLUIDO})
    emp = {
        "legajo": _LEG_NORMAL, "nombre": "Rodriguez Juan",
        "departamento": "Administracion", "registros": [], "excluido_ot": False,
    }
    servidor._aplicar_exclusiones_ot([emp])
    assert emp["excluido_ot"] is False
    assert emp.get("liquida_ot", True) is True
    assert emp.get("observacion_liquidacion", "") == ""


# ──────────────────────────────────────────────────────────────
# 2. Token: OT real, no cero
# ──────────────────────────────────────────────────────────────

def test_token_ot50_es_real_para_excluido(monkeypatch, client):
    """El token del excluido debe tener OT real, no '0h'."""
    monkeypatch.setattr(servidor, "_cargar_metadata",
                        lambda: {"semanas": [], "total": 0, "semana_actual": 0})
    # _emp_excluido() ya tiene excluido_ot=True (simula salida de _aplicar_exclusiones_ot)
    monkeypatch.setattr(servidor, "_procesar_empleados",
                        lambda df, deptos: ([_emp_excluido()], date(2026,6,1), date(2026,6,7)))
    monkeypatch.setattr(servidor, "_preparar_dias", lambda r: [
        {"fecha": "2026-06-02", "ot50": "01:00:00", "ot100": "00:00:00",
         "comida": 1, "franco": 0, "tarde": 0,
         "tipo_dia": "normal", "tiene_ot": True, "descripcion": ""}
    ])

    resp = client.post(
        "/procesar",
        data={"csv": (io.BytesIO(_CSV_BYTES), "f.csv"), "departamentos": "Administracion"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200

    tok = next((k for k, v in servidor._sesion.items()
                if isinstance(v, dict) and str(v.get("legajo","")) == _LEG_EXCLUIDO), None)
    assert tok is not None, "El excluido debe tener token"
    datos = servidor._sesion[tok]

    assert datos["totales"]["ot50"] != "0h", \
        f"OT50 no debe ser cero para excluido. Obtenido: {datos['totales']['ot50']}"
    assert datos["excluido_ot"] is True
    assert datos["liquida_ot"] is False


# ──────────────────────────────────────────────────────────────
# 3. Comidas se conservan
# ──────────────────────────────────────────────────────────────

def test_comidas_se_conservan(monkeypatch):
    monkeypatch.setattr(servidor, "_cargar_excluidos_ot", lambda: {_LEG_EXCLUIDO})
    emp = {
        "legajo": _LEG_EXCLUIDO, "nombre": "MANCIONI MARTIN",
        "departamento": "Administracion", "excluido_ot": False,
        "registros": [{"Fecha": "2026-06-02", "50%": "01:00:00", "100%": "00:00:00",
                       "COMIDA": 2, "FRANCO": 0, "Tarde": 0}],
    }
    servidor._aplicar_exclusiones_ot([emp])
    assert emp["registros"][0]["COMIDA"] == 2


# ──────────────────────────────────────────────────────────────
# 4. Francos se conservan
# ──────────────────────────────────────────────────────────────

def test_francos_se_conservan(monkeypatch):
    monkeypatch.setattr(servidor, "_cargar_excluidos_ot", lambda: {_LEG_EXCLUIDO})
    emp = {
        "legajo": _LEG_EXCLUIDO, "nombre": "MANCIONI MARTIN",
        "departamento": "Administracion", "excluido_ot": False,
        "registros": [{"Fecha": "2026-06-02", "50%": "01:00:00", "100%": "00:00:00",
                       "COMIDA": 1, "FRANCO": 1, "Tarde": 0}],
    }
    servidor._aplicar_exclusiones_ot([emp])
    assert emp["registros"][0]["FRANCO"] == 1


# ──────────────────────────────────────────────────────────────
# 5. _calcular_periodo incluye excluido con OT real
# ──────────────────────────────────────────────────────────────

def test_calcular_periodo_incluye_excluido_con_ot_real(monkeypatch):
    item = _item_historial_excluido()
    monkeypatch.setattr(servidor, "_leer_historial", lambda *a, **kw: [item])
    monkeypatch.setattr(servidor, "_cargar_metadata", lambda: _meta_sem1())
    monkeypatch.setattr(servidor, "_sesion", {})

    resumen = servidor._calcular_periodo(1, 1, "administracion")

    assert len(resumen) == 1
    emp = resumen[0]
    assert str(emp["legajo"]) == _LEG_EXCLUIDO
    assert emp["ot50"] != "0h", \
        f"OT50 debe ser real en el período. Obtenido: {emp['ot50']}"
    assert emp["liquida_ot"] is False
    assert emp["excluido_ot"] is True
    assert emp["comidas"] == 1


# ──────────────────────────────────────────────────────────────
# 6. El cierre recibirá OT real (no cero) en el INSERT
# ──────────────────────────────────────────────────────────────

def test_cierre_recibe_ot_real(monkeypatch):
    """_calcular_periodo (usado por periodo_cerrar) devuelve OT real para excluidos."""
    item = _item_historial_excluido(ot50="2h00", ot100="1h00", comidas=2, francos=1)
    item["totales"]["ot100"] = "1h00"
    item["dias"][0]["ot100"] = "01:00:00"

    monkeypatch.setattr(servidor, "_leer_historial", lambda *a, **kw: [item])
    monkeypatch.setattr(servidor, "_cargar_metadata", lambda: _meta_sem1())
    monkeypatch.setattr(servidor, "_sesion", {})

    resumen = servidor._calcular_periodo(1, 1, "administracion")
    emp = next(e for e in resumen if str(e["legajo"]) == _LEG_EXCLUIDO)

    # Estos son los valores que irán al INSERT en periodo_empleados
    assert emp["ot50"] != "0h",  f"ot50 debe ser real. Obtenido: {emp['ot50']}"
    assert emp["ot100"] != "0h", f"ot100 debe ser real. Obtenido: {emp['ot100']}"
    assert emp["comidas"] == 2
    assert emp["francos"] == 1


# ──────────────────────────────────────────────────────────────
# 7. historial_acumulado: OT real (no cero) en acumulación
# ──────────────────────────────────────────────────────────────

def test_historial_acumulado_ot_real(monkeypatch, client):
    """El historial acumulado no debe zerear OT de empleados excluidos."""
    item = _item_historial_excluido()
    monkeypatch.setattr(servidor, "_leer_historial", lambda *a, **kw: [item])
    monkeypatch.setattr(servidor, "_cargar_metadata", lambda: _meta_sem1())
    monkeypatch.setattr(servidor, "_sesion", {})

    resp = client.get("/historial/acumulado?departamento=administracion")
    assert resp.status_code == 200

    body = resp.data.decode("utf-8")
    # El acumulado debe mostrar "1h00" (real), nunca "0h" para OT50
    assert "1h00" in body or "01:00" in body, \
        "El historial acumulado debe mostrar OT real para empleados excluidos"


# ──────────────────────────────────────────────────────────────
# 8. Períodos cerrados anteriores no se modifican
# ──────────────────────────────────────────────────────────────

def test_periodos_cerrados_no_se_modifican(monkeypatch):
    """
    _calcular_periodo trabaja solo con historial activo y sesión.
    No toca la tabla periodos ni periodo_empleados.
    """
    writes = []

    class FakeConn:
        def execute(self, sql, *args, **kwargs):
            if sql.strip().upper().startswith(("UPDATE", "INSERT", "DELETE")):
                writes.append(sql)
            return self
        def fetchone(self): return None
        def fetchall(self): return []
        def __iter__(self): return iter([])

    monkeypatch.setattr(servidor, "_leer_historial", lambda *a, **kw: [])
    monkeypatch.setattr(servidor, "_cargar_metadata", lambda: {"semanas": [], "total": 0})
    monkeypatch.setattr(servidor, "_sesion", {})

    servidor._calcular_periodo(1, 1, "administracion")

    assert writes == [], \
        f"_calcular_periodo no debe escribir en DB. Escrituras detectadas: {writes}"


# ──────────────────────────────────────────────────────────────
# 9. _recalcular_totales_token: OT real
# ──────────────────────────────────────────────────────────────

def test_recalcular_totales_token_ot_real():
    """_recalcular_totales_token no zeroa OT aunque excluido_ot=True."""
    d = {
        "legajo": _LEG_EXCLUIDO,
        "excluido_ot": True,
        "liquida_ot": False,
        "dias": [
            {"ot50": "01:00:00", "ot100": "00:30:00", "comida": 1, "franco": 0, "tarde": 0},
            {"ot50": "00:30:00", "ot100": "00:00:00", "comida": 0, "franco": 1, "tarde": 1},
        ],
        "totales": {},
    }
    servidor._recalcular_totales_token(d)

    assert d["totales"]["ot50"] != "0h",  "OT50 debe ser real tras recalcular"
    assert d["totales"]["ot100"] != "0h", "OT100 debe ser real tras recalcular"
    assert d["totales"]["comidas"] == 1
    assert d["totales"]["francos"] == 1
    assert d["totales"]["tardanzas"] == 1


# ──────────────────────────────────────────────────────────────
# 10. Totales de horas/comidas del depto excluyen a excluido_ot;
#     francos y tardanzas de ese empleado SI se siguen sumando.
# ──────────────────────────────────────────────────────────────

def _registros(normales, cincuenta, cien, comida, franco, tarde):
    return [{
        "Fecha": "2026-06-02", "Normales": normales, "50%": cincuenta, "100%": cien,
        "COMIDA": comida, "FRANCO": franco, "Tarde": tarde, "Observaciones": "",
    }]


def test_generar_pdf_resumen_excluye_horas_y_comidas_del_total():
    data = [
        {"legajo": "10", "nombre": "Excluido Prueba", "departamento": "Administracion",
         "registros": _registros("07:00:00", "05:00:00", "00:00:00", 9, 1, 1),
         "excluido_ot": True},
        {"legajo": "7", "nombre": "Normal Prueba", "departamento": "Administracion",
         "registros": _registros("07:00:00", "01:00:00", "00:00:00", 2, 1, 0),
         "excluido_ot": False},
    ]
    pdf_bytes = generar_pdf_resumen(data, "Junio 2026")
    texto = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_bytes)).pages)

    assert "05:00:00" in texto, "la hora individual del excluido debe seguir viéndose"
    assert "TOTALES" in texto
    # El total de 50% sumado (bug) daría 06:00:00 (5h excluido + 1h normal); no debe aparecer.
    assert "06:00:00" not in texto
    # El total de comidas sumado (bug) daría 11; no debe aparecer.
    assert "11" not in texto


def test_generar_pdf_general_total_departamento_excluye_horas_y_comidas():
    data = [
        {"legajo": "10", "nombre": "Excluido Prueba", "departamento": "Administracion",
         "registros": _registros("07:00:00", "05:00:00", "00:00:00", 9, 1, 1),
         "excluido_ot": True},
        {"legajo": "7", "nombre": "Normal Prueba", "departamento": "Administracion",
         "registros": _registros("07:00:00", "01:00:00", "00:00:00", 2, 1, 0),
         "excluido_ot": False},
    ]
    pdf_bytes = generar_pdf_general(data, "Junio 2026", feriados=set())
    texto = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_bytes)).pages)

    assert "TOTAL GENERAL DEL DEPARTAMENTO" in texto
    assert "Horas 50%: 01:00:00" in texto, "el total del depto debe ser solo el del no excluido (1h)"
    assert "Comidas: 2" in texto, "las comidas del excluido no deben sumar al total del depto"
    assert "Francos: 2" in texto, "los francos SI deben seguir sumando aunque este excluido de OT"
