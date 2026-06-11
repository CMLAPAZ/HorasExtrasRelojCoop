# -*- coding: utf-8 -*-
"""
departamentos.py — módulo compartido de normalización de departamentos
(sin dependencias de Flask), usado por servidor.py y por
reporte_saldos_francos.py (proceso aparte, vía tarea programada).

Distingue:
- clave_canonica(nombre)  -> clave de comparación/agrupamiento
  (minúsculas, sin tildes): "redes", "administracion", "guardias",
  "internet", "telefonia".
- nombre_visible(nombre)  -> etiqueta oficial con tildes/capitalización:
  "Redes", "Administración", "Guardias", "Internet", "Telefonía".
- mismo_departamento(a, b) -> compara dos nombres por clave canónica.
"""
import departamentos as deptos


# ──────────────────────────────────────────────────────────────
# 1. Administración / administracion -> mismo departamento
# ──────────────────────────────────────────────────────────────

def test_administracion_y_administracion_sin_tilde_son_el_mismo_depto():
    assert deptos.mismo_departamento("Administración", "administracion") is True
    assert deptos.mismo_departamento("ADMINISTRACIÓN", "Admin") is True
    assert deptos.clave_canonica("Administración") == deptos.clave_canonica("administracion") == "administracion"


# ──────────────────────────────────────────────────────────────
# 2. Telefonía / telefonia -> mismo departamento
# ──────────────────────────────────────────────────────────────

def test_telefonia_y_telefonia_sin_tilde_son_el_mismo_depto():
    assert deptos.mismo_departamento("Telefonía", "telefonia") is True
    assert deptos.mismo_departamento("TELEFONIA", "Telefono") is True
    assert deptos.clave_canonica("Telefonía") == deptos.clave_canonica("telefonia") == "telefonia"


# ──────────────────────────────────────────────────────────────
# Departamentos distintos -> no se consideran iguales
# ──────────────────────────────────────────────────────────────

def test_departamentos_distintos_no_son_iguales():
    assert deptos.mismo_departamento("Redes", "Administración") is False
    assert deptos.mismo_departamento("Guardias", "Internet") is False


# ──────────────────────────────────────────────────────────────
# nombre_visible: forma canónica, alias y forma visible -> mismo resultado
# ──────────────────────────────────────────────────────────────

def test_nombre_visible_es_estable_para_los_5_canonicos():
    for canon, visible in deptos._VISIBLES.items():
        assert deptos.nombre_visible(visible) == visible          # ya visible -> idéntico
        assert deptos.nombre_visible(canon) == visible             # clave canónica -> visible
        assert deptos.nombre_visible(visible.upper()) == visible   # MAYÚSCULAS -> visible
