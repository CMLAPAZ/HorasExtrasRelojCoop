# -*- coding: utf-8 -*-
"""
Pruebas para recursos/no_enviar_reportes.json.

Regla: los empleados de no_enviar_reportes.json no aparecen en PDFs ni HTML
de mails automáticos/manuales. Sí aparecen en todo lo demás.

Casos verificados:
  1. Empleados excluidos no aparecen en datos filtrados para el mail (PDF).
  2. Empleados excluidos no aparecen en el HTML del mail.
  3. Otros empleados sí aparecen en los datos filtrados.
  4. Los datos internos (antes del filtro) conservan a todos los empleados.
  5. El filtro no modifica el diccionario original.
  6. Si no existe no_enviar_reportes.json, no se filtra nada.
"""
import reporte_saldos_francos as rrf

_LEG_MANCIONI = "10"
_LEG_GATTI    = "101"
_LEG_OTRO     = "7"


def _emp(legajo, nombre, depto="ADMINISTRACION"):
    return {
        "legajo": legajo, "nombre": nombre, "departamento": depto,
        "saldo_inicial": 2, "generados": 1, "tomados": 0, "saldo_actual": 3,
        "detalle_tomados": [],
    }


def _por_depto_base():
    return {
        "ADMINISTRACION": [
            _emp(_LEG_MANCIONI, "MANCIONI MARTIN"),
            _emp(_LEG_GATTI,    "GATTI"),
            _emp(_LEG_OTRO,     "Rodriguez Juan"),
        ]
    }


# ──────────────────────────────────────────────────────────────
# 1. Excluidos no aparecen en datos filtrados para mail/PDF
# ──────────────────────────────────────────────────────────────

def test_excluidos_no_en_datos_envio(monkeypatch):
    monkeypatch.setattr(rrf, "_leer_no_enviar_reportes",
                        lambda: {_LEG_MANCIONI, _LEG_GATTI})
    resultado = rrf._filtrar_no_enviar(_por_depto_base())
    legs = [str(e["legajo"]) for e in resultado["ADMINISTRACION"]]
    assert _LEG_MANCIONI not in legs, "Mancioni no debe aparecer en datos de envío"
    assert _LEG_GATTI    not in legs, "Gatti no debe aparecer en datos de envío"


# ──────────────────────────────────────────────────────────────
# 2. Excluidos no aparecen en el HTML del mail
# ──────────────────────────────────────────────────────────────

def test_excluidos_no_en_html_email(monkeypatch):
    monkeypatch.setattr(rrf, "_leer_no_enviar_reportes",
                        lambda: {_LEG_MANCIONI, _LEG_GATTI})
    filtrado = rrf._filtrar_no_enviar(_por_depto_base())
    html = rrf._hacer_html_email("Supervisor", ["ADMINISTRACION"], filtrado, "01/01/2026")
    assert "MANCIONI" not in html.upper(), "Mancioni no debe estar en el HTML del mail"
    assert "GATTI"    not in html.upper(), "Gatti no debe estar en el HTML del mail"


# ──────────────────────────────────────────────────────────────
# 3. Otros empleados sí aparecen en datos de envío
# ──────────────────────────────────────────────────────────────

def test_otros_empleados_si_aparecen(monkeypatch):
    monkeypatch.setattr(rrf, "_leer_no_enviar_reportes",
                        lambda: {_LEG_MANCIONI, _LEG_GATTI})
    resultado = rrf._filtrar_no_enviar(_por_depto_base())
    legs = [str(e["legajo"]) for e in resultado["ADMINISTRACION"]]
    assert _LEG_OTRO in legs, "Rodriguez Juan debe aparecer en datos de envío"


# ──────────────────────────────────────────────────────────────
# 4. Datos internos (antes del filtro) conservan a todos
# ──────────────────────────────────────────────────────────────

def test_datos_internos_conservan_excluidos():
    original = _por_depto_base()
    legs = [str(e["legajo"]) for e in original["ADMINISTRACION"]]
    assert _LEG_MANCIONI in legs, "Mancioni debe estar en datos internos"
    assert _LEG_GATTI    in legs, "Gatti debe estar en datos internos"
    assert _LEG_OTRO     in legs, "Rodriguez Juan debe estar en datos internos"


# ──────────────────────────────────────────────────────────────
# 5. El filtro no modifica el dict original
# ──────────────────────────────────────────────────────────────

def test_filtro_no_modifica_original(monkeypatch):
    monkeypatch.setattr(rrf, "_leer_no_enviar_reportes",
                        lambda: {_LEG_MANCIONI, _LEG_GATTI})
    original = _por_depto_base()
    cantidad_antes = len(original["ADMINISTRACION"])
    rrf._filtrar_no_enviar(original)
    assert len(original["ADMINISTRACION"]) == cantidad_antes, \
        "El filtro no debe mutar el dict original"


# ──────────────────────────────────────────────────────────────
# 6. Sin archivo no_enviar_reportes.json, no se filtra nada
# ──────────────────────────────────────────────────────────────

def test_sin_archivo_no_filtra(monkeypatch):
    monkeypatch.setattr(rrf, "_leer_no_enviar_reportes", lambda: set())
    resultado = rrf._filtrar_no_enviar(_por_depto_base())
    assert len(resultado["ADMINISTRACION"]) == 3, \
        "Sin archivo de exclusión, todos los empleados deben pasar"
