# NOTAS TÉCNICAS – CM_HorasExtras (v1.1.2 estable)

## Contexto

- Ajuste interno documentado en CHANGELOG: mantenimiento de constantes de comidas por **convención técnica**.
- Se conservan umbrales:
  - UMBRAL_1_COMIDA = 7h30
  - UMBRAL_2_COMIDA = 13h30
- Sin cambios funcionales. No se emite release nuevo ni tag.

## Pendientes propuestos (para branch futura)

- Regla híbrida en días hábiles: marcar 1 comida si hay ≥30' después de 13:00 (además de umbrales por bloque).
- Unificación de cálculo de comidas por bloques continuos con “cosido” de huecos ≤5'.
- Pruebas unitarias adicionales para fines de semana/feriados con múltiples tramos.

## Decisiones de ingeniería

- Se prioriza compatibilidad de reportes históricos por sobre el ajuste fino de umbrales.
- Próxima versión recomendada si se cambia lógica: v1.1.3 (patch) o v1.2.0 (minor), según alcance.
