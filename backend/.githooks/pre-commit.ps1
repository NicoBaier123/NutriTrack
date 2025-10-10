# Abort if requirements.in newer than requirements.txt
Set-Location (Split-Path $MyInvocation.MyCommand.Path -Parent) | Out-Null
Set-Location ..
if ((Get-Item requirements.in).LastWriteTimeUtc -gt (Get-Item requirements.txt).LastWriteTimeUtc) {
  Write-Error "requirements.txt ist veraltet. Bitte 'pwsh -File scripts/bootstrap.ps1' oder 'pip-compile' ausführen."
  exit 1
}
