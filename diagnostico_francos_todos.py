# -*- coding: utf-8 -*-
"""Diagnóstico de SOLO LECTURA: estado de francos_cierre_detalle para TODOS
los cierres ACTIVOS de TODOS los departamentos.

No escribe nada en la DB. Usa /admin/diagnostico-francos vía
test_request_context (mismo patrón ya usado para pid=2).

Uso (en la consola Bash de PythonAnywhere, dentro de /home/cmhoras/cm_horas):
    python3 diagnostico_francos_todos.py
"""
import servidor

servidor._autenticado = lambda: True

with servidor.app.test_request_context("/admin/diagnostico-francos", method="GET"):
    resp = servidor.admin_diagnostico_francos()
    data = resp.get_json()

print("=== TOTALES ===")
print("total cierres activos:", data["periodos"]["total"])
print("por_departamento:", data["periodos"]["por_departamento"])
print("con_snapshot:", data["periodos"]["con_snapshot"])
print("snapshot_vacio:", data["periodos"]["snapshot_vacio"])
print()

print("=== REQUIEREN CORRECCION ===")
for p in data["periodos"]["requieren_correccion"]:
    print(
        f"pid={p['periodo_id']:>4}  depto={p['departamento']!r:18}  "
        f"cerrado_en={p['cerrado_en']!r:28}  "
        f"actuales={p['registros_snapshot']:>3}  "
        f"correctos={p['registros_correctos_estimados']:>3}  "
        f"faltantes={p['registros_faltantes_estimados']:>3}  "
        f"legacy_sin_cargado_en={p['legacy_sin_cargado_en']:>2}  "
        f"ya_corregido_en={p['ya_corregido_en']!r}"
    )
if not data["periodos"]["requieren_correccion"]:
    print("  (ninguno)")

print()
print("=== CIERRES POSTERIORES POTENCIALMENTE AFECTADOS POR UNA CORRECCION ===")
for a in data["cierres_posteriores_afectados_por_correccion"]:
    print(a)
if not data["cierres_posteriores_afectados_por_correccion"]:
    print("  (ninguno)")

print()
print("=== INCONSISTENCIAS CADENA DE SALDOS (fecha_corte vs ultimo cierre activo) ===")
for i in data["inconsistencias_cadena_saldos"]:
    print(i)
if not data["inconsistencias_cadena_saldos"]:
    print("  (ninguna)")
