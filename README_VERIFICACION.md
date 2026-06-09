# Verificación rápida CM_HorasExtras (v1.1.2)

## 1) Prueba de humo (Windows PowerShell)

```powershell
cd C:\Users\USUARIO\OneDrive\Apps\CM_HorasExtras
# Copiá la carpeta 'CM_HorasExtras_verificacion_1_1_2' dentro del proyecto
.\CM_HorasExtras_verificacion_1_1_2\scripts\smoke.ps1 -Csv .\CM_HorasExtras_verificacion_1_1_2\test_data\croschek_sample.csv
```

Resultado: genera PDF en `.\salida\` y log `salida/smoke.log`.

## 2) Tests unitarios (pytest)

Requiere `pytest` instalado en tu entorno.

```powershell
pip install pytest
pytest .\CM_HorasExtras_verificacion_1_1_2\tests -q
```

## 3) Notas técnicas

Ver `docs/NOTAS_TECNICAS.md` para el detalle de la convención y pendientes.
