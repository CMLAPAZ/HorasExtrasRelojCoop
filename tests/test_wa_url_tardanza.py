# -*- coding: utf-8 -*-
"""
test_wa_url_tardanza.py — El mensaje de WhatsApp debe avisar "Llegada tarde"
en el renglon del dia, no solo en el resumen de totales (que casi nunca se
usa desde que existe el formato por-dia, ver commit 5554bb2).
"""
import urllib.parse

import pytest

import servidor


@pytest.fixture
def con_telefono(monkeypatch):
    monkeypatch.setattr(servidor, "_cargar_telefonos", lambda: {"150": "3511234567"})


def _decodificar(wa_url):
    query = wa_url.split("?text=", 1)[1]
    return urllib.parse.unquote(query)


def test_dia_con_ot_y_tardanza_incluye_llegada_tarde(con_telefono):
    dias = [{
        "fecha": "2026-08-27", "fecha_fmt": "08-27", "dia_semana": "Jueves",
        "ot50": "05:00:00", "ot100": "00:00:00",
        "franco": 0, "comida": 1, "tarde": 1,
    }]
    url = servidor._wa_url("150", "MELGAREJO MANUEL", "http://x/e/tok", dias=dias)
    texto = _decodificar(url)
    assert "Jueves 08-27: 05:00 (50%), Comida, Llegada tarde" in texto


def test_dia_sin_tardanza_no_menciona_llegada_tarde(con_telefono):
    dias = [{
        "fecha": "2026-08-28", "fecha_fmt": "08-28", "dia_semana": "Viernes",
        "ot50": "04:00:00", "ot100": "00:00:00",
        "franco": 0, "comida": 1, "tarde": 0,
    }]
    url = servidor._wa_url("150", "MELGAREJO MANUEL", "http://x/e/tok", dias=dias)
    texto = _decodificar(url)
    assert "Llegada tarde" not in texto
    assert "Viernes 08-28: 04:00 (50%), Comida" in texto


def test_dia_con_tardanza_sin_ot_ni_franco_ni_comida_igual_aparece(con_telefono):
    """Un dia con jornada normal completa (sin extras) pero llegada tarde
    no debe descartarse por los filtros de 'no tiene nada que mostrar'."""
    dias = [{
        "fecha": "2026-08-27", "fecha_fmt": "08-27", "dia_semana": "Jueves",
        "ot50": "00:00:00", "ot100": "00:00:00",
        "franco": 0, "comida": 0, "tarde": 1,
    }]
    url = servidor._wa_url("150", "MELGAREJO MANUEL", "http://x/e/tok", dias=dias)
    texto = _decodificar(url)
    assert "Jueves 08-27: Llegada tarde" in texto
