<#
instalar.ps1
Instala CM HorasExtras como aplicación de Windows para el usuario actual.
- Copia el exe y los datos a %LOCALAPPDATA%\CM_HorasExtras\
- Crea acceso directo en el Escritorio
- Crea acceso directo en el Menú Inicio

Uso (PowerShell desde la carpeta del proyecto):
  .\instalar.ps1            # instalar
  .\instalar.ps1 -Desinstalar  # quitar la instalación
#>

param([switch]$Desinstalar)

$AppName    = "CM HorasExtras"
$AppVersion = "1.3.0"
$Publisher  = "CM La Paz Online"
$ExeName    = "CM_HorasExtras.exe"
$InstallDir = "C:\APPS\CM_HorasExtras"   # carpeta de instalación real
$DistDir    = Join-Path $PSScriptRoot "dist"
$ExeSrc     = Join-Path $DistDir $ExeName
$ExeDst     = Join-Path $InstallDir $ExeName
$RegKey     = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CM_HorasExtras"

$Desktop   = [Environment]::GetFolderPath("Desktop")
$StartMenu = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"
$ShortcutDesktop   = Join-Path $Desktop   "$AppName.lnk"
$ShortcutStartMenu = Join-Path $StartMenu "$AppName.lnk"

function Write-Ok($m)   { Write-Host "[OK]   $m" -ForegroundColor Green  }
function Write-Warn($m) { Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err($m)  { Write-Host "[ERR]  $m" -ForegroundColor Red    }

# ── DESINSTALACIÓN ─────────────────────────────────────────────────────────────
if ($Desinstalar) {
    Write-Host "Desinstalando $AppName ..." -ForegroundColor Cyan
    if (Test-Path $InstallDir)        { Remove-Item -Recurse -Force $InstallDir;   Write-Ok "Carpeta de instalación eliminada." }
    if (Test-Path $ShortcutDesktop)   { Remove-Item -Force $ShortcutDesktop;       Write-Ok "Acceso directo del Escritorio eliminado." }
    if (Test-Path $ShortcutStartMenu) { Remove-Item -Force $ShortcutStartMenu;     Write-Ok "Acceso directo del Menú Inicio eliminado." }
    if (Test-Path $RegKey)            { Remove-Item -Path $RegKey -Force;           Write-Ok "Entrada de registro eliminada." }
    Write-Ok "Desinstalación completa."
    exit 0
}

# ── INSTALACIÓN ────────────────────────────────────────────────────────────────
Write-Host "Instalando $AppName ..." -ForegroundColor Cyan

# 1) Verificar que el exe existe en dist\
if (-not (Test-Path $ExeSrc)) {
    Write-Err "No se encontró $ExeSrc"
    Write-Err "Ejecutá primero: .\build_exe.ps1"
    exit 1
}

# 2) Crear carpeta de instalación
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir | Out-Null
}

# 3) Copiar exe
Copy-Item $ExeSrc $ExeDst -Force
Write-Ok "Exe copiado a $InstallDir"

# 4) Copiar / migrar config.json
#    Prioridad: config existente en InstallDir (no sobreescribir datos del usuario)
$configSrc = Join-Path $DistDir "config.json"
$configDst = Join-Path $InstallDir "config.json"
if (Test-Path $configDst) {
    Write-Warn "config.json ya existe en instalacion - no sobreescrito (se conservan datos del usuario)."
} elseif (Test-Path $configSrc) {
    Copy-Item $configSrc $configDst -Force
    Write-Ok "config.json copiado."
} else {
    # config vacío mínimo
    '{"feriados":[],"asignaciones_especiales":{},"dias_paro":{},"horarios_paro":{}}' |
        Out-File -FilePath $configDst -Encoding utf8
    Write-Ok "config.json creado (vacío)."
}

# 5) Actualizar recursos\version.txt en la instalación
$recursosDir = Join-Path $InstallDir "recursos"
if (-not (Test-Path $recursosDir)) { New-Item -ItemType Directory -Path $recursosDir | Out-Null }
Set-Content -Path (Join-Path $recursosDir "version.txt") -Value $AppVersion -Encoding utf8
Write-Ok "recursos\version.txt actualizado a v$AppVersion."

# 6) Crear carpeta reportes
$reportesDir = Join-Path $InstallDir "reportes"
if (-not (Test-Path $reportesDir)) {
    New-Item -ItemType Directory -Path $reportesDir | Out-Null
    Write-Ok "Carpeta reportes\ creada."
}

# 6) Crear accesos directos
$shell = New-Object -ComObject WScript.Shell

foreach ($lnkPath in @($ShortcutDesktop, $ShortcutStartMenu)) {
    try {
        $lnk = $shell.CreateShortcut($lnkPath)
        if ($lnk) {
            $lnk.TargetPath       = $ExeDst
            $lnk.WorkingDirectory = $InstallDir
            $lnk.IconLocation     = $ExeDst
            $lnk.Description      = "CM HorasExtras - Calculador de horas extras"
            $lnk.Save()
            Write-Ok "Acceso directo creado: $lnkPath"
        } else {
            Write-Warn "No se pudo crear acceso directo: $lnkPath"
        }
    } catch {
        Write-Warn "Error al crear acceso directo $lnkPath : $_"
    }
}

# 7) Registrar en Windows Apps (Agregar o quitar programas)
$uninstallCmd = "powershell -ExecutionPolicy Bypass -File `"$PSScriptRoot\instalar.ps1`" -Desinstalar"
New-Item         -Path $RegKey -Force | Out-Null
Set-ItemProperty -Path $RegKey -Name "DisplayName"     -Value $AppName
Set-ItemProperty -Path $RegKey -Name "DisplayVersion"  -Value $AppVersion
Set-ItemProperty -Path $RegKey -Name "Publisher"       -Value $Publisher
Set-ItemProperty -Path $RegKey -Name "InstallLocation" -Value $InstallDir
Set-ItemProperty -Path $RegKey -Name "DisplayIcon"     -Value $ExeDst
Set-ItemProperty -Path $RegKey -Name "UninstallString" -Value $uninstallCmd
Set-ItemProperty -Path $RegKey -Name "NoModify"        -Value 1 -Type DWord
Set-ItemProperty -Path $RegKey -Name "NoRepair"        -Value 1 -Type DWord
Write-Ok "Registrado en Aplicaciones de Windows (v$AppVersion)."

# 8) Resumen
Write-Host ""
Write-Host "  Instalación completa." -ForegroundColor Green
Write-Host "  Carpeta : $InstallDir" -ForegroundColor Cyan
Write-Host "  Para desinstalar: .\instalar.ps1 -Desinstalar" -ForegroundColor Gray
Write-Host ""
