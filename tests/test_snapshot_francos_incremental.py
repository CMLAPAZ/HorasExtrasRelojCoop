# -*- coding: utf-8 -*-
"""
Lógica incremental de cierres de francos (Problema 2).

Cada cierre de un departamento debe incluir únicamente los francos cuyo
`cargado_en` esté dentro de la ventana:

    fecha_corte_anterior < cargado_en <= fecha_corte_actual

donde `fecha_corte_anterior` es la fecha/hora de corte (periodos.cerrado_en)
del cierre activo (no ANULADO) anterior del **mismo departamento** — sin
límite inferior si no existe uno. Ambos extremos se comparan como string
SIN truncar microsegundos (`_normalizar_cargado_en` solo cambia 'T' por
espacio). La selección está centralizada en
`_seleccionar_francos_ventana_cierre`, usada tanto por
`_snapshot_francos_cierre` como por el diagnóstico
`/admin/corregir-francos-cierre/<pid>` — ambos caminos deben producir el
mismo conjunto.

Los francos con `cargado_en` vacío/NULL/solo espacios ("legacy", sin dato de
carga) nunca se asignan a una ventana por comparación lexicográfica: quedan
señalados aparte (`legacy_sin_cargado_en` en el diagnóstico) para revisión
manual y `_snapshot_francos_cierre` no los toca. La lista `legacy` incluye
también los registros en estado 'Cerrado' (pueden haber sido incluidos
históricamente bajo la lógica anterior y necesitar auditoría manual);
solo excluye 'Anulado'.

Si `legajos` es `None` o está vacío, `_seleccionar_francos_ventana_cierre`
devuelve `([], fecha_corte_anterior, [])` sin ejecutar ninguna selección
global — un cierre sin empleados nunca puede tocar francos de otros.

La comparación de `cargado_en` usa `_SQL_CARGADO_EN_NORM` (separador 'T' ->
espacio, recortando espacios), la misma expresión para detectar vacíos y
para ambos límites de la ventana — acepta indistintamente
'YYYY-MM-DD HH:MM:SS[.ffffff]' y 'YYYY-MM-DDTHH:MM:SS[.ffffff]'.

`_generar_pdf_francos_cierre` arma el nombre del archivo a partir de
`fecha_corte` quitando todo carácter no numérico (':', 'T', espacios, '/'),
para ser válido como nombre de archivo en Windows aun cuando `fecha_corte`
incluya hora y microsegundos.
"""
import sqlite3
from pathlib import Path

import pytest

import servidor


@pytest.fixture
def db_temporal(tmp_path, monkeypatch):
    db_file = tmp_path / "cierres_test.db"
    monkeypatch.setattr(servidor, "DATOS_DIR", tmp_path)
    monkeypatch.setattr(servidor, "DB_FILE", db_file)
    servidor._init_db()
    return db_file


@pytest.fixture(autouse=True)
def _patch_io(monkeypatch):
    monkeypatch.setattr(servidor, "_autenticado", lambda: True)


@pytest.fixture
def client():
    servidor.app.config["TESTING"] = True
    with servidor.app.test_client() as c:
        yield c


def _conn(db_file):
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    return conn


def _crear_periodo(conn, cerrado_en, departamento, legajo, nombre, estado="ACTIVO"):
    """Inserta un cierre (periodos + un periodo_empleados) y devuelve su pid."""
    cur = conn.execute(
        "INSERT INTO periodos (cerrado_en, semana_desde, semana_hasta, archivo, "
        "fecha_desde, fecha_hasta, estado) VALUES (?,?,?,?,?,?,?)",
        (cerrado_en, 1, 1, "periodo_test.json", "2026-01-01", "2026-01-07", estado),
    )
    pid = cur.lastrowid
    conn.execute(
        "INSERT INTO periodo_empleados (periodo_id,legajo,nombre,departamento,ot50,ot100,"
        "comidas,francos,tardanzas,semanas,confirmado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, legajo, nombre, departamento, "0h", "0h", 0, 0, 0, "[]", 0),
    )
    conn.commit()
    return pid


def _crear_franco(conn, legajo, nombre, cargado_en, fecha_desde, dias=1,
                   tipo="UNICO", fecha_hasta="", estado="Aprobado"):
    cur = conn.execute(
        "INSERT INTO francos_tomados (legajo, nombre, tipo, fecha_desde, fecha_hasta, "
        "fechas_sueltas, dias, estado, cargado_en) VALUES (?,?,?,?,?,?,?,?,?)",
        (legajo, nombre, tipo, fecha_desde, fecha_hasta or fecha_desde, "[]", dias, estado, cargado_en),
    )
    conn.commit()
    return cur.lastrowid


def _claves_detalle(rows):
    return {(str(r["legajo"]), r["tipo"], r["fecha_desde"] or "", r["fecha_hasta"] or "",
             r["fechas_sueltas"] or "[]", r["dias"]) for r in rows}


# ──────────────────────────────────────────────────────────────
# 1. Primer cierre del departamento: incluye todo hasta el corte actual
# ──────────────────────────────────────────────────────────────

def test_primer_cierre_incluye_todo_hasta_el_corte(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"
    _crear_franco(conn, leg, nombre, cargado_en="2026-06-01 10:00:00", fecha_desde="2026-05-01")
    _crear_franco(conn, leg, nombre, cargado_en="2026-06-05 10:00:00", fecha_desde="2026-05-15")

    pid = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    servidor._snapshot_francos_cierre(conn, pid, "2026-06-10 12:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    detalle = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid,)).fetchall()
    assert {r["fecha_desde"] for r in detalle} == {"2026-05-01", "2026-05-15"}


# ──────────────────────────────────────────────────────────────
# 2. Segundo cierre del mismo departamento: solo lo posterior al corte
#    anterior; no repite francos del cierre anterior
# ──────────────────────────────────────────────────────────────

def test_segundo_cierre_excluye_lo_ya_incluido_en_el_anterior(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    _crear_franco(conn, leg, nombre, cargado_en="2026-06-01 10:00:00", fecha_desde="2026-05-01")
    pid1 = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    servidor._snapshot_francos_cierre(conn, pid1, "2026-06-10 12:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    _crear_franco(conn, leg, nombre, cargado_en="2026-06-15 10:00:00", fecha_desde="2026-06-12")
    pid2 = _crear_periodo(conn, "2026-06-20T12:00:00.000000", "Redes", leg, nombre)
    servidor._snapshot_francos_cierre(conn, pid2, "2026-06-20 12:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    detalle1 = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid1,)).fetchall()
    detalle2 = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid2,)).fetchall()

    assert {r["fecha_desde"] for r in detalle1} == {"2026-05-01"}
    assert {r["fecha_desde"] for r in detalle2} == {"2026-06-12"}  # no repite el de pid1


# ──────────────────────────────────────────────────────────────
# 3. Cierre anterior de OTRO departamento no se toma como límite
# ──────────────────────────────────────────────────────────────

def test_cierre_anterior_de_otro_departamento_no_es_limite(db_temporal):
    conn = _conn(db_temporal)

    # Cierre de Administración con corte posterior a la carga del franco de Redes
    pid_admin = _crear_periodo(conn, "2026-06-15T12:00:00.000000", "Administración", "10", "PEREZ")
    servidor._snapshot_francos_cierre(conn, pid_admin, "2026-06-15 12:00:00", legajos=["10"], departamento="administracion")
    conn.commit()

    leg, nombre = "133", "ZABALA ANTONIO"
    _crear_franco(conn, leg, nombre, cargado_en="2026-06-01 10:00:00", fecha_desde="2026-05-01")

    pid_redes = _crear_periodo(conn, "2026-06-20T12:00:00.000000", "Redes", leg, nombre)
    servidor._snapshot_francos_cierre(conn, pid_redes, "2026-06-20 12:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    detalle = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid_redes,)).fetchall()
    assert {r["fecha_desde"] for r in detalle} == {"2026-05-01"}


# ──────────────────────────────────────────────────────────────
# 4. Cierre anterior ANULADO no se toma como límite
# ──────────────────────────────────────────────────────────────

def test_cierre_anterior_anulado_no_es_limite(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    pid1 = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    conn.execute("UPDATE periodos SET estado='ANULADO' WHERE id=?", (pid1,))
    conn.commit()

    _crear_franco(conn, leg, nombre, cargado_en="2026-06-01 10:00:00", fecha_desde="2026-05-01")

    pid2 = _crear_periodo(conn, "2026-06-20T12:00:00.000000", "Redes", leg, nombre)
    servidor._snapshot_francos_cierre(conn, pid2, "2026-06-20 12:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    detalle = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid2,)).fetchall()
    assert {r["fecha_desde"] for r in detalle} == {"2026-05-01"}


# ──────────────────────────────────────────────────────────────
# 5. Varios cierres anteriores: se utiliza el corte válido inmediatamente
#    anterior (no el más viejo)
# ──────────────────────────────────────────────────────────────

def test_varios_cierres_anteriores_usa_el_corte_inmediato_anterior(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    _crear_periodo(conn, "2026-06-05T12:00:00.000000", "Redes", leg, nombre)
    _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    pid3 = _crear_periodo(conn, "2026-06-20T12:00:00.000000", "Redes", leg, nombre)

    anterior = servidor._fecha_corte_anterior(conn, pid3, "Redes", "2026-06-20 12:00:00")
    # Se preservan los microsegundos del cerrado_en del cierre anterior (no se trunca)
    assert anterior == "2026-06-10 12:00:00.000000"


# ──────────────────────────────────────────────────────────────
# 5b. El "anterior" se determina por cerrado_en, no por el orden de los ids
# ──────────────────────────────────────────────────────────────

def test_orden_anterior_no_depende_solo_del_id(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    # pid_a (id menor) tiene un cerrado_en POSTERIOR al de pid_b (id mayor)
    pid_a = _crear_periodo(conn, "2026-06-20T12:00:00.000000", "Redes", leg, nombre)
    pid_b = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    assert pid_a < pid_b

    pid_c = _crear_periodo(conn, "2026-06-30T12:00:00.000000", "Redes", leg, nombre)

    anterior = servidor._fecha_corte_anterior(conn, pid_c, "Redes", "2026-06-30 12:00:00.000000")
    # Debe ser el corte de pid_a (más reciente), no el de pid_b (id mayor pero corte más viejo)
    assert anterior == "2026-06-20 12:00:00.000000"


# ──────────────────────────────────────────────────────────────
# 6. Dos cierres el mismo día con horas distintas se separan correctamente
# ──────────────────────────────────────────────────────────────

def test_dos_cierres_mismo_dia_horas_distintas_se_separan(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    _crear_franco(conn, leg, nombre, cargado_en="2026-06-10 08:00:00", fecha_desde="2026-05-01")
    pid1 = _crear_periodo(conn, "2026-06-10T09:00:00.000000", "Redes", leg, nombre)
    servidor._snapshot_francos_cierre(conn, pid1, "2026-06-10 09:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    _crear_franco(conn, leg, nombre, cargado_en="2026-06-10 12:00:00", fecha_desde="2026-06-02")
    pid2 = _crear_periodo(conn, "2026-06-10T18:00:00.000000", "Redes", leg, nombre)
    servidor._snapshot_francos_cierre(conn, pid2, "2026-06-10 18:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    detalle1 = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid1,)).fetchall()
    detalle2 = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid2,)).fetchall()

    assert {r["fecha_desde"] for r in detalle1} == {"2026-05-01"}
    assert {r["fecha_desde"] for r in detalle2} == {"2026-06-02"}


# ──────────────────────────────────────────────────────────────
# 7. Límite inferior: cargado_en == fecha_corte_anterior queda excluido
# ──────────────────────────────────────────────────────────────

def test_limite_inferior_igual_a_corte_anterior_excluido(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    pid1 = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    servidor._snapshot_francos_cierre(conn, pid1, "2026-06-10 12:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    # Cargado exactamente en el instante del corte anterior
    _crear_franco(conn, leg, nombre, cargado_en="2026-06-10 12:00:00", fecha_desde="2026-06-08")

    pid2 = _crear_periodo(conn, "2026-06-20T12:00:00.000000", "Redes", leg, nombre)
    servidor._snapshot_francos_cierre(conn, pid2, "2026-06-20 12:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    detalle2 = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid2,)).fetchall()
    assert detalle2 == []


# ──────────────────────────────────────────────────────────────
# 8. Límite superior: cargado_en == fecha_corte_actual queda incluido
# ──────────────────────────────────────────────────────────────

def test_limite_superior_igual_a_corte_actual_incluido(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    _crear_franco(conn, leg, nombre, cargado_en="2026-06-10 12:00:00", fecha_desde="2026-06-08")
    pid1 = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    servidor._snapshot_francos_cierre(conn, pid1, "2026-06-10 12:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    detalle1 = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid1,)).fetchall()
    assert {r["fecha_desde"] for r in detalle1} == {"2026-06-08"}


# ──────────────────────────────────────────────────────────────
# 9. Posterior al corte actual queda excluido
# ──────────────────────────────────────────────────────────────

def test_posterior_al_corte_actual_excluido(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    _crear_franco(conn, leg, nombre, cargado_en="2026-06-10 12:00:01", fecha_desde="2026-06-08")
    pid1 = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    servidor._snapshot_francos_cierre(conn, pid1, "2026-06-10 12:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    detalle1 = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid1,)).fetchall()
    assert detalle1 == []


# ──────────────────────────────────────────────────────────────
# 10. _snapshot_francos_cierre y el diagnóstico de "correctos" devuelven
#     exactamente el mismo conjunto
# ──────────────────────────────────────────────────────────────

def test_snapshot_y_diagnostico_correctos_coinciden(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    # Cierre 1 de Redes, ya con su snapshot
    _crear_franco(conn, leg, nombre, cargado_en="2026-06-01 10:00:00", fecha_desde="2026-05-01")
    pid1 = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    servidor._snapshot_francos_cierre(conn, pid1, "2026-06-10 12:00:00", legajos=[leg], departamento="redes")
    conn.commit()

    # Francos cargados después del cierre 1, antes del cierre 2
    _crear_franco(conn, leg, nombre, cargado_en="2026-06-12 09:00:00", fecha_desde="2026-06-08", dias=1)
    _crear_franco(conn, leg, nombre, cargado_en="2026-06-18 09:00:00", fecha_desde="2026-06-15", dias=2)

    # Cierre 2 de Redes, todavía SIN snapshot
    pid2 = _crear_periodo(conn, "2026-06-20T12:00:00.000000", "Redes", leg, nombre)
    conn.commit()

    resp = client.get(f"/admin/corregir-francos-cierre/{pid2}")
    diag = resp.get_json()
    correctos_claves = _claves_detalle(diag["faltantes"])

    servidor._snapshot_francos_cierre(conn, pid2, "2026-06-20 12:00:00", legajos=[leg], departamento="redes")
    conn.commit()
    detalle2 = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid2,)).fetchall()

    assert correctos_claves == _claves_detalle(detalle2)
    assert {"2026-06-08", "2026-06-15"} == {r["fecha_desde"] for r in detalle2}


# ──────────────────────────────────────────────────────────────
# 11. Corrección de un cierre histórico usa su propia ventana temporal
# ──────────────────────────────────────────────────────────────

def test_correccion_cierre_historico_usa_su_propia_ventana(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    pid1 = _crear_periodo(conn, "2026-06-05T12:00:00.000000", "Redes", leg, nombre)
    pid2 = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    _crear_periodo(conn, "2026-06-20T12:00:00.000000", "Redes", leg, nombre)
    conn.commit()

    # Pertenece a la ventana de pid2: (pid1_corte, pid2_corte]
    _crear_franco(conn, leg, nombre, cargado_en="2026-06-07 09:00:00", fecha_desde="2026-06-06")
    # Pertenece a la ventana de pid3 (cierre global más reciente), no a la de pid2
    _crear_franco(conn, leg, nombre, cargado_en="2026-06-15 09:00:00", fecha_desde="2026-06-14")

    resp = client.get(f"/admin/corregir-francos-cierre/{pid2}")
    diag = resp.get_json()

    # cerrado_en se guardó con microsegundos (".000000") y _normalizar_cargado_en
    # ya no los trunca
    assert diag["fecha_corte"] == "2026-06-10 12:00:00.000000"
    assert diag["fecha_corte_anterior"] == "2026-06-05 12:00:00.000000"
    assert {f["fecha_desde"] for f in diag["faltantes"]} == {"2026-06-06"}


# ──────────────────────────────────────────────────────────────
# 12. _normalizar_cargado_en: preserva microsegundos, no trunca
# ──────────────────────────────────────────────────────────────

def test_normalizar_cargado_en_preserva_microsegundos():
    assert servidor._normalizar_cargado_en("2026-06-11T14:32:05.123456") == "2026-06-11 14:32:05.123456"


def test_normalizar_cargado_en_sin_microsegundos():
    assert servidor._normalizar_cargado_en("2026-06-11T14:32:05") == "2026-06-11 14:32:05"


def test_normalizar_cargado_en_valor_vacio():
    assert servidor._normalizar_cargado_en("") == ""
    assert servidor._normalizar_cargado_en(None) == ""


# ──────────────────────────────────────────────────────────────
# 13. Dos cierres dentro del mismo segundo, con microsegundos distintos:
#     no se trunca cerrado_en -> no se duplica el franco cargado en ese
#     segundo (queda solo en el primer cierre)
# ──────────────────────────────────────────────────────────────

def test_dos_cierres_mismo_segundo_microsegundos_distintos_no_duplica(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    cerrado_en_1 = "2026-06-10T12:00:00.100000"
    cerrado_en_2 = "2026-06-10T12:00:00.900000"
    fecha_corte_1 = servidor._normalizar_cargado_en(cerrado_en_1)
    fecha_corte_2 = servidor._normalizar_cargado_en(cerrado_en_2)
    assert fecha_corte_1 != fecha_corte_2  # se conserva la diferencia de microsegundos

    # cargado_en solo tiene precisión de segundos (= 12:00:00.000000): cae
    # ANTES de fecha_corte_1 (12:00:00.100000) -> pertenece al primer cierre
    _crear_franco(conn, leg, nombre, cargado_en="2026-06-10 12:00:00", fecha_desde="2026-06-08")

    pid1 = _crear_periodo(conn, cerrado_en_1, "Redes", leg, nombre)
    servidor._snapshot_francos_cierre(conn, pid1, fecha_corte_1, legajos=[leg], departamento="redes")
    conn.commit()

    pid2 = _crear_periodo(conn, cerrado_en_2, "Redes", leg, nombre)

    anterior_pid2 = servidor._fecha_corte_anterior(conn, pid2, "Redes", fecha_corte_2)
    assert anterior_pid2 == fecha_corte_1  # corte de pid1, con microsegundos preservados

    servidor._snapshot_francos_cierre(conn, pid2, fecha_corte_2, legajos=[leg], departamento="redes")
    conn.commit()

    detalle1 = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid1,)).fetchall()
    detalle2 = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid2,)).fetchall()

    assert {r["fecha_desde"] for r in detalle1} == {"2026-06-08"}
    assert detalle2 == []  # no se duplica en el segundo cierre


# ──────────────────────────────────────────────────────────────
# 14. Dos cierres con cerrado_en EXACTAMENTE igual: el de menor id se
#     considera "anterior" (ventana completa); el de mayor id no duplica
# ──────────────────────────────────────────────────────────────

def test_dos_cierres_mismo_cerrado_en_exacto_se_desempata_por_id(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    cerrado_en = "2026-06-10T12:00:00.500000"
    fecha_corte = servidor._normalizar_cargado_en(cerrado_en)

    _crear_franco(conn, leg, nombre, cargado_en="2026-06-01 10:00:00", fecha_desde="2026-05-01")

    pid1 = _crear_periodo(conn, cerrado_en, "Redes", leg, nombre)
    pid2 = _crear_periodo(conn, cerrado_en, "Redes", leg, nombre)
    assert pid1 < pid2

    anterior_pid1 = servidor._fecha_corte_anterior(conn, pid1, "Redes", fecha_corte)
    anterior_pid2 = servidor._fecha_corte_anterior(conn, pid2, "Redes", fecha_corte)
    assert anterior_pid1 == ""            # pid1 (menor id): sin anterior -> ventana completa
    assert anterior_pid2 == fecha_corte   # pid2 (mayor id): acotado por pid1 -> ventana vacía

    servidor._snapshot_francos_cierre(conn, pid1, fecha_corte, legajos=[leg], departamento="redes")
    servidor._snapshot_francos_cierre(conn, pid2, fecha_corte, legajos=[leg], departamento="redes")
    conn.commit()

    detalle1 = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid1,)).fetchall()
    detalle2 = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid2,)).fetchall()

    assert {r["fecha_desde"] for r in detalle1} == {"2026-05-01"}
    assert detalle2 == []  # no duplica


# ──────────────────────────────────────────────────────────────
# 15. cargado_en vacío / NULL / solo espacios ("legacy"): nunca se asignan
#     a una ventana por comparación lexicográfica; quedan señalados aparte
# ──────────────────────────────────────────────────────────────

def test_cargado_en_vacio_no_entra_y_se_reporta_como_legacy(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    _crear_franco(conn, leg, nombre, cargado_en="", fecha_desde="2026-06-01")

    pid = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    fecha_corte = servidor._normalizar_cargado_en("2026-06-10T12:00:00.000000")

    resp = client.get(f"/admin/corregir-francos-cierre/{pid}")
    diag = resp.get_json()
    assert {f["fecha_desde"] for f in diag["legacy_sin_cargado_en"]} == {"2026-06-01"}
    assert diag["faltantes"] == []  # no se cuela en la ventana

    servidor._snapshot_francos_cierre(conn, pid, fecha_corte, legajos=[leg], departamento="redes")
    conn.commit()
    detalle = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid,)).fetchall()
    assert detalle == []


def test_cargado_en_null_no_entra_y_se_reporta_como_legacy(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    conn.execute(
        "INSERT INTO francos_tomados (legajo, nombre, tipo, fecha_desde, fecha_hasta, "
        "fechas_sueltas, dias, estado, cargado_en) VALUES (?,?,?,?,?,?,?,?,NULL)",
        (leg, nombre, "UNICO", "2026-06-01", "2026-06-01", "[]", 1, "Aprobado"),
    )
    conn.commit()

    pid = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    fecha_corte = servidor._normalizar_cargado_en("2026-06-10T12:00:00.000000")

    resp = client.get(f"/admin/corregir-francos-cierre/{pid}")
    diag = resp.get_json()
    assert {f["fecha_desde"] for f in diag["legacy_sin_cargado_en"]} == {"2026-06-01"}
    assert diag["faltantes"] == []

    servidor._snapshot_francos_cierre(conn, pid, fecha_corte, legajos=[leg], departamento="redes")
    conn.commit()
    detalle = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid,)).fetchall()
    assert detalle == []


def test_cargado_en_solo_espacios_no_entra_y_se_reporta_como_legacy(db_temporal, client):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    _crear_franco(conn, leg, nombre, cargado_en="   ", fecha_desde="2026-06-01")

    pid = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    fecha_corte = servidor._normalizar_cargado_en("2026-06-10T12:00:00.000000")

    resp = client.get(f"/admin/corregir-francos-cierre/{pid}")
    diag = resp.get_json()
    assert {f["fecha_desde"] for f in diag["legacy_sin_cargado_en"]} == {"2026-06-01"}
    assert diag["faltantes"] == []

    servidor._snapshot_francos_cierre(conn, pid, fecha_corte, legajos=[leg], departamento="redes")
    conn.commit()
    detalle = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid,)).fetchall()
    assert detalle == []


# ──────────────────────────────────────────────────────────────
# 16. _snapshot_francos_cierre y _seleccionar_francos_ventana_cierre (el
#     mismo helper que usa el diagnóstico) devuelven el mismo conjunto
# ──────────────────────────────────────────────────────────────

def test_snapshot_y_helper_compartido_devuelven_el_mismo_conjunto(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    _crear_franco(conn, leg, nombre, cargado_en="2026-06-01 10:00:00", fecha_desde="2026-05-01")
    _crear_franco(conn, leg, nombre, cargado_en="2026-06-05 10:00:00", fecha_desde="2026-05-15")

    pid = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    fecha_corte = servidor._normalizar_cargado_en("2026-06-10T12:00:00.000000")

    rows_helper, _, _ = servidor._seleccionar_francos_ventana_cierre(conn, pid, [leg], "redes", fecha_corte)

    servidor._snapshot_francos_cierre(conn, pid, fecha_corte, legajos=[leg], departamento="redes")
    conn.commit()
    detalle = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid,)).fetchall()

    assert len(detalle) == 2
    assert _claves_detalle(rows_helper) == _claves_detalle(detalle)


# ──────────────────────────────────────────────────────────────
# 17. Cierre sin legajos: nunca selecciona francos de otros empleados
# ──────────────────────────────────────────────────────────────

def test_sin_legajos_no_selecciona_nada(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    _crear_franco(conn, leg, nombre, cargado_en="2026-06-01 10:00:00", fecha_desde="2026-05-01")
    _crear_franco(conn, "999", "OTRO EMPLEADO", cargado_en="2026-06-01 10:00:00", fecha_desde="2026-05-02")

    pid = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    fecha_corte = servidor._normalizar_cargado_en("2026-06-10T12:00:00.000000")

    rows_vacio, anterior_vacio, legacy_vacio = servidor._seleccionar_francos_ventana_cierre(
        conn, pid, [], "redes", fecha_corte)
    assert rows_vacio == []
    assert legacy_vacio == []

    rows_none, anterior_none, legacy_none = servidor._seleccionar_francos_ventana_cierre(
        conn, pid, None, "redes", fecha_corte)
    assert rows_none == []
    assert legacy_none == []
    assert anterior_none == anterior_vacio  # fecha_corte_anterior se calcula igual en ambos casos

    servidor._snapshot_francos_cierre(conn, pid, fecha_corte, legajos=[], departamento="redes")
    conn.commit()

    detalle = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid,)).fetchall()
    assert detalle == []

    # Ningún franco de ningún empleado fue tocado por el cierre sin legajos
    estados = {r["legajo"]: r["estado"] for r in conn.execute("SELECT legajo, estado FROM francos_tomados")}
    assert estados[leg] == "Aprobado"
    assert estados["999"] == "Aprobado"


# ──────────────────────────────────────────────────────────────
# 18. Legacy sin cargado_en: incluye 'Cerrado' (auditoría histórica),
#     excluye 'Anulado'; ninguno entra a la ventana ni al snapshot
# ──────────────────────────────────────────────────────────────

def test_legacy_incluye_cerrado_y_excluye_anulado(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    _crear_franco(conn, leg, nombre, cargado_en="", fecha_desde="2026-06-01", estado="Aprobado")
    _crear_franco(conn, leg, nombre, cargado_en="", fecha_desde="2026-06-02", estado="Cerrado")
    _crear_franco(conn, leg, nombre, cargado_en="", fecha_desde="2026-06-03", estado="Anulado")

    pid = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    fecha_corte = servidor._normalizar_cargado_en("2026-06-10T12:00:00.000000")

    rows, _, legacy = servidor._seleccionar_francos_ventana_cierre(conn, pid, [leg], "redes", fecha_corte)

    assert rows == []  # cargado_en vacío nunca entra a la ventana
    legacy_por_fecha = {r["fecha_desde"]: r["estado"] for r in legacy}
    assert legacy_por_fecha == {"2026-06-01": "Aprobado", "2026-06-02": "Cerrado"}
    assert "2026-06-03" not in legacy_por_fecha  # Anulado nunca aparece como legacy

    servidor._snapshot_francos_cierre(conn, pid, fecha_corte, legajos=[leg], departamento="redes")
    conn.commit()
    detalle = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid,)).fetchall()
    assert detalle == []  # ninguno de los legacy se incorpora automáticamente


# ──────────────────────────────────────────────────────────────
# 19. cargado_en con separador 'T' y microsegundos se normaliza igual que
#     'YYYY-MM-DD HH:MM:SS[.ffffff]' para la comparación de la ventana
# ──────────────────────────────────────────────────────────────

def test_cargado_en_con_t_y_microsegundos_se_normaliza(db_temporal):
    conn = _conn(db_temporal)
    leg, nombre = "133", "ZABALA ANTONIO"

    _crear_franco(conn, leg, nombre, cargado_en="2026-06-10T11:59:59.999999", fecha_desde="2026-06-08")

    pid = _crear_periodo(conn, "2026-06-10T12:00:00.000000", "Redes", leg, nombre)
    fecha_corte = servidor._normalizar_cargado_en("2026-06-10T12:00:00.000000")

    servidor._snapshot_francos_cierre(conn, pid, fecha_corte, legajos=[leg], departamento="redes")
    conn.commit()

    detalle = conn.execute("SELECT * FROM francos_cierre_detalle WHERE periodo_id=?", (pid,)).fetchall()
    assert {r["fecha_desde"] for r in detalle} == {"2026-06-08"}


# ──────────────────────────────────────────────────────────────
# 20. Nombre de archivo del PDF de francos del cierre: solo dígitos,
#     válido en Windows aun cuando fecha_corte tiene ':'/'T'/microsegundos
# ──────────────────────────────────────────────────────────────

def test_generar_pdf_francos_cierre_nombre_seguro_windows():
    pid = "round3test999999"
    fecha_corte = "2026-06-10 12:00:00.123456"

    esperado = Path(f"reportes/francos_cierre_{pid}_20260610120000123456.pdf")
    if esperado.exists():
        esperado.unlink()
    try:
        servidor._generar_pdf_francos_cierre(pid, [], fecha_corte)
        assert esperado.exists()
        assert ":" not in esperado.name
        assert " " not in esperado.name
        assert "/" not in esperado.name
        assert "T" not in esperado.name
    finally:
        if esperado.exists():
            esperado.unlink()


# ──────────────────────────────────────────────────────────────
# 21. (suite completa) — ver resultado de `pytest` para todo el proyecto
# ──────────────────────────────────────────────────────────────
