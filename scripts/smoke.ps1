    Param(
      [string]$Csv = ".\test_data\croschek_sample.csv"
    )
    Write-Host ">>> Smoke test CM_HorasExtras (v1.1.2 estable)"
    if (!(Test-Path $Csv)) { throw "No existe $Csv" }
    # Asume main.py acepta --csv y genera un PDF en ./salida/
    python .\main.py --csv $Csv --out .\salida\ 2>&1 | Tee-Object -FilePath ".\salida\smoke.log"
    if (!(Test-Path ".\salida")) { throw "No se creó carpeta salida" }
    Write-Host "OK. Revisá la carpeta '.\salida' y el log 'smoke.log'."
