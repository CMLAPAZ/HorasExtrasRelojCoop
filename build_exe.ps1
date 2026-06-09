<#
build_exe.ps1
Construye CM_HorasExtras.exe usando PyInstaller con el spec oficial.
Uso (PowerShell desde la carpeta del proyecto):
  .\build_exe.ps1          # compilar con CM_HorasExtras.spec
  .\build_exe.ps1 -Force   # limpiar build/dist antes sin preguntar

El exe resultante queda en dist\CM_HorasExtras.exe, junto con config.json
copiado automáticamente. La carpeta dist\ es lo que se distribuye al usuario.
#>

param(
    [switch]$Force
)

function Write-Ok($m)   { Write-Host "[OK]   $m" -ForegroundColor Green  }
function Write-Warn($m) { Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err($m)  { Write-Host "[ERR]  $m" -ForegroundColor Red    }

Set-Location $PSScriptRoot

# 1) Localizar Python del venv
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Err "No se encontró .venv\Scripts\python.exe. Creá el entorno virtual primero."
    exit 1
}
Write-Host "Python: $python"

# 2) Verificar PyInstaller
$ver = & $python -m PyInstaller --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Instalando PyInstaller..."
    & $python -m pip install pyinstaller | Out-Default
    if ($LASTEXITCODE -ne 0) { Write-Err "No se pudo instalar PyInstaller."; exit 1 }
}
Write-Ok "PyInstaller $($ver)"

# 3) Limpiar carpetas previas
if ($Force) {
    if (Test-Path .\build) { Remove-Item -Recurse -Force .\build }
    if (Test-Path .\dist)  { Remove-Item -Recurse -Force .\dist  }
    Write-Ok "build/ dist limpiadas."
} elseif ((Test-Path .\build) -or (Test-Path .\dist)) {
    Write-Host "Se detectaron build/ o dist/. ¿Limpiar antes de compilar? (s/n)"
    $r = Read-Host
    if ($r -imatch '^s') {
        if (Test-Path .\build) { Remove-Item -Recurse -Force .\build }
        if (Test-Path .\dist)  { Remove-Item -Recurse -Force .\dist  }
        Write-Ok "build/ dist limpiadas."
    }
}

# 4) Build
Write-Host "`nCompilando con CM_HorasExtras.spec ..." -ForegroundColor Cyan
& $python -m PyInstaller CM_HorasExtras.spec --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Err "PyInstaller falló (código $LASTEXITCODE)."
    exit $LASTEXITCODE
}
Write-Ok "Build completado."

# 5) Copiar archivos de usuario junto al exe
$dist = Join-Path $PSScriptRoot "dist"

# config.json — contiene feriados, horarios_paro, asignaciones_especiales
if (Test-Path (Join-Path $PSScriptRoot "config.json")) {
    Copy-Item (Join-Path $PSScriptRoot "config.json") (Join-Path $dist "config.json") -Force
    Write-Ok "config.json copiado a dist\"
} else {
    Write-Warn "config.json no encontrado; el exe lo creará vacío al primer uso."
}

# Carpeta reportes (para que el exe tenga donde guardar PDFs)
$reportesDir = Join-Path $dist "reportes"
if (-not (Test-Path $reportesDir)) {
    New-Item -ItemType Directory -Path $reportesDir | Out-Null
    Write-Ok "Carpeta dist\reportes\ creada."
}

# 6) Resultado final
$exe = Join-Path $dist "CM_HorasExtras.exe"
if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Ok "Exe listo: $exe ($size MB)"
    Write-Host ""
    Write-Host "  Para distribuir, comprime la carpeta dist\ completa." -ForegroundColor Green
    Write-Host "  El usuario solo necesita: CM_HorasExtras.exe + config.json + reportes\" -ForegroundColor Green
} else {
    Write-Warn "No se encontró el exe en dist\. Revisá los logs de build."
}
