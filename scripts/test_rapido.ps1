# Launcher del smoke test (autocontenido)
$here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$smoke = Join-Path $here "..\CM_HorasExtras_verificacion_1_1_2\scripts\smoke.ps1"

if (!(Test-Path $smoke)) { throw "No se encontró: $smoke" }

# Ejecutar con bypass solo para esta corrida
powershell -NoProfile -ExecutionPolicy Bypass -File $smoke
