#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parcha el cierre de Redes ya cerrado para agregar a Karen Soto (legajo 102)
en periodos.saldo_anterior, y actualiza su fecha_corte en francos_saldo_inicial.

Ejecutar UNA VEZ en PythonAnywhere:
  cd /home/cmhoras/cm_horas && python fix_karen_soto_cierre.py
"""
import sqlite3, json
from datetime import datetime

DB_FILE = "datos/cierres.db"

conn = sqlite3.connect(DB_FILE)
conn.row_factory = sqlite3.Row

# Buscar el cierre de Redes (o el último cierre de redes no anulado)
cierres_redes = conn.execute("""
    SELECT p.id, p.fecha_hasta, p.cerrado_en, p.saldo_anterior
    FROM periodos p
    WHERE LOWER(p.departamento) LIKE '%redes%'
       OR p.id IN (
           SELECT DISTINCT pe.periodo_id FROM periodo_empleados pe
           WHERE LOWER(pe.departamento) LIKE '%redes%'
       )
    AND COALESCE(p.estado,'ACTIVO') != 'ANULADO'
    ORDER BY p.id DESC
""").fetchall()

if not cierres_redes:
    # Buscar por periodo_empleados
    cierres_redes = conn.execute("""
        SELECT p.id, p.fecha_hasta, p.cerrado_en, p.saldo_anterior
        FROM periodos p
        JOIN periodo_empleados pe ON pe.periodo_id = p.id
        WHERE LOWER(pe.departamento) LIKE '%redes%'
        AND COALESCE(p.estado,'ACTIVO') != 'ANULADO'
        GROUP BY p.id
        ORDER BY p.id DESC
    """).fetchall()

print(f"Cierres de Redes encontrados: {len(cierres_redes)}")
for c in cierres_redes:
    sn = json.loads(c["saldo_anterior"] or "{}")
    print(f"  #{c['id']} hasta {c['fecha_hasta']} — {len(sn)} empleados en saldo_anterior")

if not cierres_redes:
    print("No se encontraron cierres de Redes.")
    conn.close()
    exit()

# Tomar el más reciente
cierre = cierres_redes[0]
pid = cierre["id"]
fecha_corte = cierre["cerrado_en"] or datetime.now().isoformat()

saldo_ant = json.loads(cierre["saldo_anterior"] or "{}")

# Verificar si Karen ya está
if "102" in saldo_ant:
    print(f"\nKaren Soto (102) ya está en saldo_anterior del cierre #{pid}:")
    print(f"  {saldo_ant['102']}")
else:
    # Leer datos de Karen desde francos_saldo_inicial
    karen = conn.execute(
        "SELECT * FROM francos_saldo_inicial WHERE CAST(legajo AS TEXT)='102'"
    ).fetchone()

    if not karen:
        print("Karen Soto (102) no encontrada en francos_saldo_inicial.")
        conn.close()
        exit()

    saldo_ant["102"] = {
        "saldo":              karen["saldo"] or 0,
        "tomados_al_corte":   karen["tomados_al_corte"] or 0,
        "gen_extra_al_corte": karen["gen_extra_al_corte"] or 0,
        "fecha_corte":        karen["fecha_corte"] or "2026-05-21",
    }
    print(f"\nAgregando Karen Soto (102) a saldo_anterior del cierre #{pid}:")
    print(f"  {saldo_ant['102']}")

    conn.execute(
        "UPDATE periodos SET saldo_anterior=? WHERE id=?",
        (json.dumps(saldo_ant, ensure_ascii=False), pid)
    )

# Actualizar fecha_corte de Karen en francos_saldo_inicial (para que no doble-cuente en próximo cierre)
ahora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
conn.execute("""
    UPDATE francos_saldo_inicial
    SET fecha_corte=?, nota=?, cargado_en=?
    WHERE CAST(legajo AS TEXT)='102'
""", (
    fecha_corte[:19],
    f"fecha_corte actualizada al cierre Redes #{pid}",
    ahora_str,
))
print(f"\nActualizada fecha_corte de Karen (102) → {fecha_corte[:16]}")

conn.commit()
conn.close()
print("\n✓ Listo. Regenerá el informe completo del cierre desde /periodos/ver/<id>")
