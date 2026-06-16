#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ejecutar UNA VEZ en PythonAnywhere después del deploy para corregir
francos_saldo_inicial del último cierre que no se actualizó.

Uso:
  cd /home/cmhoras/cm_horas
  python fix_saldo_inicial.py
"""
import sqlite3, json
from datetime import datetime
from pathlib import Path

DB_FILE = Path("datos/cierres.db")

def get_db():
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn

def main():
    with get_db() as conn:
        # 1. Verificar/agregar columnas nuevas
        for col in (
            "tomados_al_corte INTEGER DEFAULT 0",
            "gen_extra_al_corte INTEGER DEFAULT 0",
            "fecha_corte TEXT DEFAULT '2026-05-21'",
        ):
            try:
                conn.execute(f"ALTER TABLE francos_saldo_inicial ADD COLUMN {col}")
                print(f"  Columna agregada: {col.split()[0]}")
            except Exception:
                pass  # ya existe

        # 2. Buscar el último cierre por departamento (no anulado)
        cierres = conn.execute("""
            SELECT p.id, p.cerrado_en, p.fecha_hasta,
                   pe.departamento,
                   GROUP_CONCAT(pe.legajo) as legajos
            FROM periodos p
            JOIN periodo_empleados pe ON pe.periodo_id = p.id
            WHERE COALESCE(p.estado, 'ACTIVO') != 'ANULADO'
            GROUP BY p.id, pe.departamento
            ORDER BY p.id DESC
        """).fetchall()

        if not cierres:
            print("No hay cierres en la DB.")
            return

        # Mostrar cierres disponibles
        print("\nCierres encontrados (más recientes primero):")
        for i, c in enumerate(cierres[:10]):
            print(f"  [{i}] #{c['id']} — {c['departamento']} — hasta {c['fecha_hasta']} — cerrado {(c['cerrado_en'] or '')[:16]}")

        idx = input("\n¿Qué cierre corregir? (número entre corchetes, Enter para el primero): ").strip()
        cierre = cierres[int(idx)] if idx.isdigit() else cierres[0]
        pid = cierre["id"]
        fecha_hasta = cierre["fecha_hasta"]
        cerrado_en  = cierre["cerrado_en"] or datetime.now().isoformat()
        legajos_str = cierre["legajos"] or ""
        legajos = [l.strip() for l in legajos_str.split(",") if l.strip()]

        print(f"\nCorrigiendo cierre #{pid} — hasta {fecha_hasta} — legajos: {legajos}")

        # 3. Leer francos_saldo_inicial actuales (ya tienen saldo pero sin tomados_al_corte/fecha_corte)
        iniciales = {}
        for r in conn.execute("SELECT * FROM francos_saldo_inicial"):
            iniciales[str(r["legajo"])] = dict(r)

        # 4. Calcular saldo_actual para cada legajo del cierre
        #    Fórmula: saldo_inicial_viejo + gen_periodos + gen_extra + gen_parcial - tomados
        all_pe = conn.execute("""
            SELECT pe.legajo, pe.francos, p.fecha_hasta
            FROM periodo_empleados pe
            JOIN periodos p ON pe.periodo_id = p.id
            WHERE COALESCE(p.estado,'ACTIVO') != 'ANULADO'
        """).fetchall()

        gen_manual_raw = {r["legajo"]: (r["total"] or 0) for r in conn.execute(
            "SELECT legajo, SUM(dias) as total FROM francos_generados GROUP BY legajo")}
        gen_parcial    = {r["legajo"]: (r["total"] or 0) for r in conn.execute(
            "SELECT legajo, SUM(dias) as total FROM francos_semana_parcial GROUP BY legajo")}
        gen_manual_sem = {r["legajo"]: (r["total"] or 0) for r in conn.execute(
            "SELECT legajo, SUM(dias) as total FROM francos_semana_manual GROUP BY legajo")}
        tomados_raw    = {r["legajo"]: (r["total"] or 0) for r in conn.execute(
            "SELECT legajo, SUM(dias) as total FROM francos_tomados WHERE COALESCE(estado,'') != 'Anulado' GROUP BY legajo")}

        tomados_totales   = tomados_raw
        gen_extra_totales = {}
        for leg, v in gen_manual_raw.items():
            gen_extra_totales[leg] = gen_extra_totales.get(leg, 0) + v
        for leg, v in gen_manual_sem.items():
            gen_extra_totales[leg] = gen_extra_totales.get(leg, 0) + v

        ahora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        actualizados = 0
        for leg in legajos:
            ini = iniciales.get(leg, {})
            si  = ini.get("saldo", 0) or 0
            old_corte     = ini.get("fecha_corte", "2026-05-21") or "2026-05-21"
            old_t_corte   = ini.get("tomados_al_corte", 0) or 0
            old_ge_corte  = ini.get("gen_extra_al_corte", 0) or 0

            # gen_periodos: períodos con fecha_hasta > corte anterior
            gen_per = sum(
                (r["francos"] or 0) for r in all_pe
                if str(r["legajo"]) == leg and (r["fecha_hasta"] or "") > old_corte
            )
            gen_extra_total = gen_manual_raw.get(leg, 0) + gen_manual_sem.get(leg, 0)
            gen = gen_per + max(0, gen_extra_total - old_ge_corte) + gen_parcial.get(leg, 0)
            tom = max(0, tomados_raw.get(leg, 0) - old_t_corte)
            saldo_actual = si + gen - tom

            # Nombre desde periodo_empleados del cierre
            row_pe = conn.execute(
                "SELECT nombre FROM periodo_empleados WHERE periodo_id=? AND legajo=?",
                (pid, leg)
            ).fetchone()
            nombre = row_pe["nombre"] if row_pe else ini.get("nombre", leg)

            conn.execute("""
                INSERT INTO francos_saldo_inicial
                    (legajo, nombre, saldo, nota, cargado_en, tomados_al_corte, gen_extra_al_corte, fecha_corte)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(legajo) DO UPDATE SET
                    saldo              = excluded.saldo,
                    nota               = excluded.nota,
                    cargado_en         = excluded.cargado_en,
                    tomados_al_corte   = excluded.tomados_al_corte,
                    gen_extra_al_corte = excluded.gen_extra_al_corte,
                    fecha_corte        = excluded.fecha_corte
            """, (
                leg, nombre, saldo_actual,
                f"Corregido manualmente post-cierre #{pid} ({cerrado_en[:16]})",
                ahora_str,
                tomados_totales.get(leg, 0),
                gen_extra_totales.get(leg, 0),
                cerrado_en,
            ))
            print(f"  Legajo {leg} ({nombre}): saldo_inicial → {saldo_actual} | tomados_al_corte={tomados_totales.get(leg,0)} | fecha_corte={cerrado_en[:16]}")
            actualizados += 1

        conn.commit()
        print(f"\n✓ {actualizados} empleados actualizados en francos_saldo_inicial.")

if __name__ == "__main__":
    main()
