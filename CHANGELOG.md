# CHANGELOG

## [1.1.2] - 2025-09-XX
### Ajustes internos (sin cambio de versión)
- Mantenimiento de constantes de comidas por **convención técnica**.
- Se conservan los umbrales establecidos:
  - `UMBRAL_1_COMIDA = 7h30`
  - `UMBRAL_2_COMIDA = 13h30`
- Aunque el criterio operativo sugerido es de **14h30**, se mantiene el valor anterior para garantizar compatibilidad con reportes históricos.
- No se realizaron cambios funcionales ni en la estructura del cálculo.
- Se conserva la versión `1.1.2` como base estable.

---

## [1.1.0] - 2025-08-28
### Añadido
- Release 1.1.0: mejoras menores en el cálculo de comidas durante fines de semana y feriados.
- Se incorpora `recursos/version.txt` y la constante `VERSION` en `main.py` para trazabilidad interna.

---

## [1.0.0] - Baseline
### Inicial
- Primera versión instalada (baseline).
- Implementación base de lectura de fichadas, cálculo de horas normales, extras, feriados y generación del informe PDF.
## [1.1.2-verificación] – 2025-10-09
✅ Verificación de entorno finalizada con éxito.
- Se validó el `main.py` en ruta `C:\Users\USUARIO\OneDrive\Apps\CM_HorasExtras`.
- Se ejecutó correctamente con `croschek_sample.csv`.
- Generación automática de carpeta `salida` OK.
- PDF e informes generados sin errores.
- Estructura de carpetas de verificación: `CM_HorasExtras_verificacion_1_1_2` confirmada.
- Script de smoke test actualizado para autodetectar `main.py`.

🔹 Estado: **Estable y listo para build v1.1.2 final.**
