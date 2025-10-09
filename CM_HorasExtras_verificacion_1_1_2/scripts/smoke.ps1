Param(
  [string]$Csv = $null,
  [string]$OutDir = $null
)

Write-Host ">>> Smoke test CM_HorasExtras (v1.1.2 estable)"

# Raíz del repo (smoke.ps1 está en ...\CM_HorasExtras_verificacion_1_1_2\scripts)
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

# main.py en la raíz del proyecto
$scriptPath = Join-Path $root "main.py"
if (!(Test-Path $scriptPath)) {
  Write-Host "Contenido en raíz ($root):"
  Get-ChildItem $root | Select Name,Length,Mode | Format-Table
  throw "No se encontró main.py en $root"
}

# CSV por defecto si no pasaste -Csv
if (-not $Csv) {
  $Csv = Join-Path $root "CM_HorasExtras_verificacion_1_1_2\test_data\croschek_sample.csv"
}
if (!(Test-Path $Csv)) { throw "No existe el archivo CSV: $Csv" }

# Carpeta salida por defecto si no pasaste -OutDir
if (-not $OutDir) { $OutDir = Join-Path $root "salida" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$log = Join-Path $OutDir "smoke.log"

# Python: prioriza venv si existe (sin operador ternario)
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
  $python = $venvPy
} else {
  $python = "python"
}

# Ejecutar
& $python $scriptPath --csv $Csv --out $OutDir 2>&1 | Tee-Object -FilePath $log

if ($LASTEXITCODE -ne 0) {
  Write-Warning "Código de salida $LASTEXITCODE. Últimas líneas del log:"
  Get-Content $log -Tail 40
  throw "Smoke fallido"
}

Write-Host "OK. Revisá '$OutDir' y el log '$log'."
