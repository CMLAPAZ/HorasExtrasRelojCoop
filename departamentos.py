# -*- coding: utf-8 -*-
"""
Normalización centralizada de nombres de departamento.

Sin dependencias de Flask ni del resto del proyecto: lo usan tanto
servidor.py (app web) como reporte_saldos_francos.py (proceso independiente,
ejecutado mediante una tarea programada) para que un mismo departamento
(Redes, Administración, Guardias, Internet, Telefonía) se agrupe y compare
igual sin importar mayúsculas, tildes, espacios o alias usados en cada
fuente de datos.
"""
import re
import unicodedata

# Alias → clave canónica (lowercase, sin tildes) de cada departamento.
_ALIASES = {
    "redes": "redes", "rede": "redes", "red": "redes",
    "administracion": "administracion", "administraciom": "administracion",
    "administrativo": "administracion", "admin": "administracion",
    "guardias": "guardias", "guardia": "guardias",
    "internet": "internet",
    "telefonia": "telefonia", "telefono": "telefonia", "telefonos": "telefonia",
    "todos": "todos",
}

# Clave canónica → nombre visible oficial (con tildes y capitalización).
_VISIBLES = {
    "redes": "Redes",
    "administracion": "Administración",
    "guardias": "Guardias",
    "internet": "Internet",
    "telefonia": "Telefonía",
}


def clave_canonica(nombre):
    """Normaliza un nombre de departamento a su clave canónica:
    minúsculas, sin tildes, espacios colapsados, alias resueltos.
    Útil como clave de agrupamiento/comparación (ej. dict keys)."""
    texto = (nombre or "").strip()
    base = unicodedata.normalize("NFKD", texto)
    base = "".join(c for c in base if not unicodedata.combining(c)).lower()
    base = re.sub(r"[^a-z0-9]+", " ", base).strip()
    return _ALIASES.get(base, base)


def nombre_visible(nombre):
    """Devuelve el nombre visible oficial (con tildes y capitalización)
    para los departamentos canónicos. Si `nombre` no corresponde a uno de
    ellos, devuelve el valor original sin modificar."""
    canon = clave_canonica(nombre)
    return _VISIBLES.get(canon, nombre or "")


def mismo_departamento(a, b):
    """True si `a` y `b` representan el mismo departamento, sin importar
    mayúsculas, tildes, espacios o alias reconocidos."""
    return clave_canonica(a) == clave_canonica(b)
