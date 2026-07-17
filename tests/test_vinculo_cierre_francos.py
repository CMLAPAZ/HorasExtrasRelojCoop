# -*- coding: utf-8 -*-
"""Asociación exacta de movimientos manuales con cierres de francos."""
import sqlite3

import servidor


def test_vincula_solo_movimientos_pendientes_y_dentro_del_corte():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE francos_tomados (
            id INTEGER PRIMARY KEY, legajo TEXT, fecha_desde TEXT,
            estado TEXT, estado_antes_cierre TEXT DEFAULT '', cierre_francos_id INTEGER
        );
        CREATE TABLE francos_generados (
            id INTEGER PRIMARY KEY, legajo TEXT, cierre_francos_id INTEGER
        );
        CREATE TABLE francos_semana_manual (
            id INTEGER PRIMARY KEY, legajo TEXT, mes TEXT,
            cierre_francos_id INTEGER
        );
        INSERT INTO francos_tomados VALUES
            (1, '100', '2026-06-10', 'Aprobado', '', NULL),
            (2, '100', '2026-07-01', 'Aprobado', '', NULL),
            (3, '101', '2026-06-15', 'Anulado', '', NULL),
            (4, '101', '2026-06-20', 'Cerrado', 'Aprobado', 8),
            (5, '113', '2026-06-10', 'Aprobado', '', NULL);
        INSERT INTO francos_generados VALUES
            (1, '100', NULL), (2, '101', 8), (3, '113', NULL);
        INSERT INTO francos_semana_manual VALUES
            (1, '100', '2026-06', NULL),
            (2, '101', '2026-07', NULL),
            (3, '113', '2026-06', NULL);
    """)

    cantidades = servidor._vincular_movimientos_cierre_francos(
        conn, 9, ["100", "101"], "2026-06-30"
    )

    assert cantidades == {"tomados": 1, "generados": 1, "semanales": 1}
    assert conn.execute(
        "SELECT estado, cierre_francos_id FROM francos_tomados WHERE id=1"
    ).fetchone() == ("Cerrado", 9)
    assert conn.execute(
        "SELECT cierre_francos_id FROM francos_tomados WHERE id=2"
    ).fetchone()[0] is None
    assert conn.execute(
        "SELECT cierre_francos_id FROM francos_tomados WHERE id=4"
    ).fetchone()[0] == 8
    assert conn.execute(
        "SELECT cierre_francos_id FROM francos_generados WHERE id=1"
    ).fetchone()[0] == 9
    assert conn.execute(
        "SELECT cierre_francos_id FROM francos_semana_manual WHERE id=1"
    ).fetchone()[0] == 9
    assert conn.execute(
        "SELECT cierre_francos_id FROM francos_semana_manual WHERE id=2"
    ).fetchone()[0] is None
    assert conn.execute(
        "SELECT cierre_francos_id FROM francos_generados WHERE id=3"
    ).fetchone()[0] is None
