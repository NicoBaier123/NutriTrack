Param(
  [switch]$Upgrade,       # optional: alle Pins auf neuere kompatible Versionen heben
  [switch]$ForceReinstall # optional: erzwingt Neuinstallation
)

$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path $MyInvocation.MyCommand.Path -Parent) | Out-Null
Set-Location ..  # -> backend/

# 0) venv sicherstellen
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  Write-Host "Creating .venv ..."
  py -3 -m venv .venv
}

$venvPy = ".\.venv\Scripts\python.exe"
$venvPip = "$venvPy -m pip"

# 1) pip + pip-tools aktualisieren
Invoke-Expression "$venvPip install --upgrade pip"
Invoke-Expression "$venvPip install --upgrade pip-tools"

# 2) requirements.in Defaults, falls nicht vorhanden
if (-not (Test-Path "requirements.in")) {
@"
fastapi
uvicorn[standard]
sqlmodel
SQLAlchemy
pydantic
requests
rapidfuzz
python-dotenv
"@ | Out-File -Encoding UTF8 requirements.in
}

# 3) requirements.txt (Lockfile) automatisch bauen/aktualisieren
$reqIn = "requirements.in"
$reqTxt = "requirements.txt"
$compileArgs = "--generate-hashes --output-file $reqTxt"
if ($Upgrade) { $compileArgs = "--upgrade " + $compileArgs }

# compile nur wenn nötig (oder Upgrade erzwungen)
$needsCompile = $Upgrade
if (-not $needsCompile) {
  if (-not (Test-Path $reqTxt)) { $needsCompile = $true }
  else {
    $needsCompile = ((Get-Item $reqIn).LastWriteTimeUtc -gt (Get-Item $reqTxt).LastWriteTimeUtc)
  }
}
if ($needsCompile) {
  Write-Host "Compiling $reqIn -> $reqTxt ..."
  & .\.venv\Scripts\pip-compile.exe $reqIn $compileArgs
}

# 4) (optional) Dev-Dependencies
if (Test-Path "requirements-dev.in") {
  $devTxt = "requirements-dev.txt"
  $compileArgsDev = "--generate-hashes --output-file $devTxt"
  if ($Upgrade) { $compileArgsDev = "--upgrade " + $compileArgsDev }
  $needsCompileDev = (-not (Test-Path $devTxt)) -or ((Get-Item "requirements-dev.in").LastWriteTimeUtc -gt (Get-Item $devTxt).LastWriteTimeUtc) -or $Upgrade
  if ($needsCompileDev) {
    & .\.venv\Scripts\pip-compile.exe requirements-dev.in $compileArgsDev
  }
}

# 5) Installation: strikt nach Lockfiles (pip-sync räumt Altlasten weg)
Invoke-Expression "$venvPip install --upgrade pip-tools"
$syncCmd = ".\.venv\Scripts\pip-sync.exe $reqTxt"
if (Test-Path "requirements-dev.txt") { $syncCmd += " requirements-dev.txt" }
if ($ForceReinstall) {
  # pip-sync hat kein --force; Workaround: uninstall all und dann pip install erneut
  & .\.venv\Scripts\pip-sync.exe  # normaler sync (schnell)
} else {
  & cmd /c $syncCmd
}

# 6) .env anlegen (falls fehlt)
if (-not (Test-Path ".env")) {
@"
FDC_API_KEY=HIER_DEIN_KEY
FDC_BASE_URL=https://api.nal.usda.gov/fdc
"@ | Out-File -Encoding UTF8 .env
  Write-Host "Created .env (fülle FDC_API_KEY)."
}

Write-Host "Bootstrap done ✅"
