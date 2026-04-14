# CHANGELOG

## [1.2.0] - 2026-04-14

### Corregido
- **Bug crítico — tardanza:** la primera entrada del día se derivaba de los eventos crudos, ignorando la imputación de tramos de madrugada al día anterior. Ahora se deriva desde `por_dia` (ya corregido), eliminando falsos positivos de tardanza en días con turno nocturno previo.
- **Bug crítico — `feriados_gui`:** `guardar_feriados()` sobreescribía todo `config.json` con solo `{"feriados": [...]}`, destruyendo `asignaciones_especiales`, `dias_paro` y otras claves. Ahora lee el config completo, actualiza solo la clave `feriados` y reescribe todo.

### Limpieza de código (`procesador.py`)
- Eliminadas funciones dead code nunca llamadas: `evaluar_tardanza`, `_es_cercana_a_6`, `_mapa_primeras_entradas`, `_es_dia_habil_comparable`, `_entrada_habil_anterior_y_siguiente`.
- Eliminados imports sin uso: `from typing import Optional`, `import os`, `import sys`.
- Eliminado `print("[DEBUG FRANJA] ...")` que quedó activo en producción e imprimía por cada empleado/día procesado.

### Mejoras de interfaz (UI)
- **Fuente global:** Segoe UI en toda la aplicación (botones, labels, entries, Treeview).
- **Tema ttk `vista`:** Treeview, Combobox y Scrollbar con estilo Windows moderno.
- **Scrollbars:** agregadas en Listbox de selección de archivo, Treeview de detalle (vertical + horizontal) y Listbox de feriados.
- **`abrir_gestor_horarios_paro`:** reescrito con geometría fija, formulario en frame con fondo, botones coloreados y **botón Cerrar** que antes no existía.
- **Ventana principal:** logo reducido, padding ajustado, botón "Gestionar feriados" en el marco principal, label de versión al pie, `resizable=False`.
- **`feriados_gui`:** scrollbar, tres botones en una sola fila (Agregar / Eliminar / Cerrar), ventana dimensionada correctamente.
- Geometrías normalizadas en todos los diálogos para eliminar espacio en blanco excesivo.
- Paleta de colores unificada con constantes (`C_PRI`, `C_OK`, `C_DEL`, `C_WARN`, `C_NEU`).

### Infraestructura
- `launch.json` actualizado: configuración "sin debug (rápido)" para ejecución directa sin overhead de debugpy; `justMyCode: true` en modo debug.

---

## [1.1.3] - 2025-11-05
### Cambiado
- **Normales limitadas a 7:00** por día hábil (independiente de la hora de ingreso).
- **Extras 50%**: excedente sobre 7:00 hasta las 21:00.
- **Extras 100%**: desde las 21:00; si el tramo cruza 21:00 y la cola es < 30’, se reclasifica a **50%**.
- **Minutos previos al inicio** no computan (se deja observación: *Entrada anticipada (recortada al inicio)*).
- **Detección multi-bloque** por día/departamento (05:00, 05:30, 06:00, 06:30; tolerancia ±12’, quórum 3 / 60%).
- **“Salida anticipada” silenciada** (no se imprime en Observaciones).

### Sin cambios
- Fines de semana y feriados: todo **100%**; **FRANCO = 1** si el 100% redondeado ≥ 4:00.
- Redondeo: solo extras (50% y 100%) a horas enteras (≥ 30’ → 1 h). Normales no se redondean.

---

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

---

## [1.1.2-verificación] – 2025-10-09
✅ Verificación de entorno finalizada con éxito.
- Se validó el `main.py` en ruta `C:\Users\USUARIO\OneDrive\Apps\CM_HorasExtras`.
- Se ejecutó correctamente con `croschek_sample.csv`.
- Generación automática de carpeta `salida` OK.
- PDF e informes generados sin errores.
- Estructura de carpetas de verificación: `CM_HorasExtras_verificacion_1_1_2` confirmada.
- Script de smoke test actualizado para autodetectar `main.py`.

🔹 Estado: **Estable y listo para build v1.1.2 final.**

---

[Unreleased]: https://github.com/CMLAPAZ/HorasExtrasRelojCoop/compare/v1.1.3...HEAD
[1.1.3]: https://github.com/CMLAPAZ/HorasExtrasRelojCoop/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/CMLAPAZ/HorasExtrasRelojCoop/compare/v1.1.0...v1.1.2
[1.1.0]: https://github.com/CMLAPAZ/HorasExtrasRelojCoop/compare/v1.0.0...v1.1.0
