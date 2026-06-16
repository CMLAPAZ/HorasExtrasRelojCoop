# -*- coding: utf-8 -*-
"""Diagnóstico de SOLO LECTURA: estado de francos_saldo_inicial vs. el último
cierre ACTIVO de un departamento (default: Redes).

Abre la DB en modo read-only (file:...?mode=ro) -- no escribe nada.

Uso (en la consola Bash de PythonAnywhere, dentro de /home/cmhoras/cm_horas):
    python3 diagnostico_saldo_redes.py
    python3 diagnostico_saldo_redes.py Administracion
"""
import sqlite3
import sys
import json
import os

DEPTO = sys.argv[1] if len(sys.argv) > 1 else "Redes"
DB_PATH = os.path.join("datos", "cierres.db")


def normalizar_cargado_en(v):
    return (v or "").replace("T", " ")


def main():
    uri = f"file:{os.path.abspath(DB_PATH)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    # Cierres ACTIVOS del depto, mas recientes primero
    cierres = conn.execute("""
        SELECT p.id, p.cerrado_en, p.fecha_desde, p.fecha_hasta, p.estado,
               p.saldo_anterior, p.francos_corregido_en,
               (SELECT pe.departamento FROM periodo_empleados pe
                WHERE pe.periodo_id = p.id LIMIT 1) AS departamento
        FROM periodos p
        WHERE COALESCE(p.estado,'ACTIVO') = 'ACTIVO'
        ORDER BY p.cerrado_en DESC
    """).fetchall()

    cierres_depto = [c for c in cierres if (c["departamento"] or "").strip().lower().startswith(DEPTO[:3].lower())]

    print(f"=== Cierres ACTIVOS para depto ~'{DEPTO}' (mas reciente primero) ===")
    for c in cierres_depto[:5]:
        print(f"  pid={c['id']:>4}  cerrado_en={c['cerrado_en']!r:32}  "
              f"fecha={c['fecha_desde']}..{c['fecha_hasta']}  depto_raw={c['departamento']!r}  "
              f"francos_corregido_en={c['francos_corregido_en']!r}")

    if not cierres_depto:
        print("  (no se encontraron cierres ACTIVOS para ese departamento)")
        conn.close()
        return

    ultimo = cierres_depto[0]
    pid = ultimo["id"]
    fecha_corte = normalizar_cargado_en(ultimo["cerrado_en"] or "")

    print()
    print(f"=== Detalle del ultimo cierre: pid={pid} ===")
    print(f"  cerrado_en (normalizado): {fecha_corte!r}")
    print(f"  fecha_desde/fecha_hasta: {ultimo['fecha_desde']} .. {ultimo['fecha_hasta']}")
    print(f"  francos_corregido_en:    {ultimo['francos_corregido_en']!r}")

    saldo_ant_raw = ultimo["saldo_anterior"]
    try:
        saldo_ant = json.loads(saldo_ant_raw) if saldo_ant_raw else {}
    except Exception:
        saldo_ant = None
    vacio = not saldo_ant_raw or saldo_ant_raw.strip() in ("", "{}", "null")
    print(f"  saldo_anterior (raw):    {saldo_ant_raw!r}")
    print(f"  saldo_anterior VACIO?:   {vacio}  "
          f"{'<<< sugiere que el bloque de actualizacion de saldo_inicial NO corrio (try/except silencioso)' if vacio else ''}")

    cnt_detalle = conn.execute(
        "SELECT COUNT(*) FROM francos_cierre_detalle WHERE periodo_id=?", (pid,)
    ).fetchone()[0]
    print(f"  francos_cierre_detalle (snapshot): {cnt_detalle} registro(s)")

    legajos = [str(r["legajo"]) for r in conn.execute(
        "SELECT DISTINCT legajo FROM periodo_empleados WHERE periodo_id=?", (pid,)
    )]
    print(f"  legajos del cierre: {legajos}")

    print()
    print(f"=== francos_saldo_inicial por legajo (cierre pid={pid}, cerrado_en[:10]={fecha_corte[:10]!r}) ===")
    for leg in legajos:
        r = conn.execute(
            "SELECT * FROM francos_saldo_inicial WHERE legajo=?", (leg,)
        ).fetchone()
        if not r:
            print(f"  legajo={leg:>5}  (SIN registro en francos_saldo_inicial)")
            continue
        fc = (r["fecha_corte"] or "")[:10]
        coincide = fc == fecha_corte[:10]
        print(f"  legajo={leg:>5}  nombre={r['nombre']!r:28} saldo={r['saldo']!s:>4}  "
              f"tomados_al_corte={r['tomados_al_corte']!s:>4}  gen_extra_al_corte={r['gen_extra_al_corte']!s:>4}  "
              f"fecha_corte={fc!r:12}  cargado_en={r['cargado_en']!r}")
        print(f"           fecha_corte == cerrado_en del ultimo cierre?  {coincide}"
              f"{'' if coincide else '   <<< DESACTUALIZADO'}")

    conn.close()


if __name__ == "__main__":
    main()
