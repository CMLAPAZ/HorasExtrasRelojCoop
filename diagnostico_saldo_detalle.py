# -*- coding: utf-8 -*-
"""Diagnóstico de SOLO LECTURA: detalle de saldo para legajos puntuales.

Muestra, para cada legajo:
  - la fila completa de francos_saldo_inicial (saldo, tomados_al_corte,
    gen_extra_al_corte, fecha_corte, cargado_en, nota)
  - todas las filas de francos_tomados (con cargado_en)
  - las filas de francos_cierre_detalle del cierre indicado (default pid=2)
  - el resultado de _calcular_saldos() para ese legajo
    (saldo_inicial, generados, tomados, saldo_actual)

No escribe nada en la DB.

Uso (en la consola Bash de PythonAnywhere, dentro de /home/cmhoras/cm_horas):
    python3 diagnostico_saldo_detalle.py 127 140 143 100
    python3 diagnostico_saldo_detalle.py 127 140 143 100 --pid 2
"""
import sys
import servidor

servidor._autenticado = lambda: True

args = sys.argv[1:]
pid = 2
if "--pid" in args:
    i = args.index("--pid")
    pid = int(args[i + 1])
    args = args[:i] + args[i + 2:]

legajos = args or ["127", "140", "143", "100"]

saldos = {str(s["legajo"]): s for s in servidor._calcular_saldos()}

with servidor._get_db() as conn:
    for leg in legajos:
        print("=" * 70)
        print(f"LEGAJO {leg}")
        print("=" * 70)

        si = conn.execute("SELECT * FROM francos_saldo_inicial WHERE legajo=?", (leg,)).fetchone()
        if si:
            print("francos_saldo_inicial:")
            print(f"  saldo={si['saldo']}  tomados_al_corte={si['tomados_al_corte']}  "
                  f"gen_extra_al_corte={si['gen_extra_al_corte']}  fecha_corte={si['fecha_corte']!r}")
            print(f"  cargado_en={si['cargado_en']!r}")
            print(f"  nota={si['nota']!r}")
        else:
            print("francos_saldo_inicial: (sin fila)")

        print()
        print("francos_tomados:")
        rows = conn.execute(
            "SELECT id, tipo, fecha_desde, fecha_hasta, fechas_sueltas, dias, estado, cargado_en "
            "FROM francos_tomados WHERE legajo=? ORDER BY cargado_en", (leg,)
        ).fetchall()
        if not rows:
            print("  (ninguno)")
        for r in rows:
            print(f"  id={r['id']:>4}  tipo={r['tipo']:<7}  {r['fecha_desde']}..{r['fecha_hasta']}  "
                  f"dias={r['dias']:>2}  estado={r['estado']!r:12}  cargado_en={r['cargado_en']!r}")

        print()
        print(f"francos_cierre_detalle (pid={pid}):")
        rows = conn.execute(
            "SELECT tipo, fecha_desde, fecha_hasta, fechas_sueltas, dias, estado "
            "FROM francos_cierre_detalle WHERE periodo_id=? AND legajo=?", (pid, leg)
        ).fetchall()
        if not rows:
            print("  (ninguno)")
        tot = 0
        for r in rows:
            print(f"  tipo={r['tipo']:<7}  {r['fecha_desde']}..{r['fecha_hasta']}  "
                  f"dias={r['dias']:>2}  estado={r['estado']!r}")
            tot += r["dias"] or 0
        print(f"  TOTAL dias snapshot pid={pid}: {tot}")

        print()
        s = saldos.get(leg)
        if s:
            print(f"_calcular_saldos(): saldo_inicial={s['saldo_inicial']}  "
                  f"generados={s['generados']}  tomados={s['tomados']}  "
                  f"saldo_actual={s['saldo_actual']}")
        else:
            print("_calcular_saldos(): (legajo no encontrado)")
        print()
